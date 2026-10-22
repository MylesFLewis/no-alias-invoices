"""Microsoft Graph connection for one independently authorised local installation."""
import base64
import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import msal

AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["https://graph.microsoft.com/Mail.Send"]
GRAPH_SEND = "https://graph.microsoft.com/v1.0/me/sendMail"
VERIFY_URL = "https://microsoft.com/devicelogin"
LOCK = threading.RLock()
FLOW_LOCK = threading.RLock()
FLOW = None
LAST_START = 0
GUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"


def client_id():
    value=os.getenv("MICROSOFT_CLIENT_ID","").strip()
    if not re.fullmatch(GUID,value):
        raise ValueError("Set a valid MICROSOFT_CLIENT_ID in the container.")
    return value


def _path(name):
    data=Path(os.getenv("DATA_DIR","/data"))
    data.mkdir(parents=True,exist_ok=True)
    return data/name


def _cache_path():
    return _path("microsoft-token-cache.json")


@contextmanager
def storage_lock():
    with LOCK:
        fd=os.open(_path("microsoft-connection.lock"),os.O_CREAT|os.O_RDWR,0o600)
        try:
            os.fchmod(fd,0o600)
            fcntl.flock(fd,fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN)
            os.close(fd)


def _private_write(path,text):
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,prefix=".microsoft-",delete=False) as file:
            temporary=Path(file.name)
            os.fchmod(file.fileno(),0o600)
            file.write(text);file.flush();os.fsync(file.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def _load():
    cache=msal.SerializableTokenCache()
    path=_cache_path()
    if path.exists():
        try:
            os.chmod(path,0o600)
            if path.stat().st_size>4*1024*1024:raise ValueError()
            cache.deserialize(path.read_text(encoding="utf-8"))
        except Exception:
            raise RuntimeError("Microsoft connection data could not be read. Check appdata permissions or reconnect.") from None
    return cache


def _save(cache):
    if cache.has_state_changed:
        _private_write(_cache_path(),cache.serialize())


def _metadata():
    path=_path("microsoft-account.json")
    if not path.exists():return {"generation":0}
    try:
        if path.stat().st_size>16384:raise ValueError()
        value=json.loads(path.read_text())
        if type(value.get("generation")) is not int:raise ValueError()
        return value
    except Exception:
        raise RuntimeError("Microsoft connection settings could not be read. Check appdata permissions.") from None


def _set_metadata(value):
    _private_write(_path("microsoft-account.json"),json.dumps(value))


def _app(identifier,cache):
    return msal.PublicClientApplication(identifier,authority=AUTHORITY,token_cache=cache,timeout=10)


def _identity(cache,identifier,metadata):
    if metadata.get("client_id") not in (None,identifier):return None
    accounts=list(cache.search(msal.TokenCache.CredentialType.ACCOUNT))
    refresh=list(cache.search(msal.TokenCache.CredentialType.REFRESH_TOKEN,query={"client_id":identifier}))
    access=list(cache.search(msal.TokenCache.CredentialType.ACCESS_TOKEN,query={"client_id":identifier}))
    homes={token.get("home_account_id") for token in refresh+access}
    accounts=[account for account in accounts if account.get("home_account_id") in homes]
    if metadata.get("home_account_id"):
        accounts=[a for a in accounts if a.get("home_account_id")==metadata["home_account_id"]]
    if len(accounts)!=1:return None
    account=accounts[0]
    username=account.get("username","").strip()
    if len(username)>254 or any(ord(c)<33 or ord(c)>126 for c in username) or not re.fullmatch(r"[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+",username):return None
    return {"username":username,"home_account_id":account["home_account_id"]}


def connection_info(identifier=None):
    identifier=identifier or client_id()
    with storage_lock():
        identity=_identity(_load(),identifier,_metadata())
    return identity


def access_token(identifier):
    with storage_lock():
        cache=_load();metadata=_metadata();identity=_identity(cache,identifier,metadata)
        if not identity:return None
        application=_app(identifier,cache)
        accounts=[a for a in application.get_accounts() if a.get("home_account_id")==identity["home_account_id"]]
        result=application.acquire_token_silent(SCOPES,account=accounts[0]) if len(accounts)==1 else None
        _save(cache)
    return result.get("access_token") if isinstance(result,dict) else None


def _owner(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value):
        raise ValueError("Reload Settings to start a Microsoft connection.")
    return hashlib.sha256(value.encode()).hexdigest()


def _expire():
    global FLOW
    if FLOW and FLOW["expires_at"]<=time.time():
        FLOW=None


def verification_uri(value):
    if not isinstance(value,str):raise ValueError('Microsoft did not supply a sign-in URL.')
    parsed=urlsplit(value)
    if (parsed.scheme!='https' or parsed.netloc not in ('microsoft.com','www.microsoft.com')
            or parsed.path not in ('/link','/devicelogin') or parsed.query or parsed.fragment):
        raise ValueError('Microsoft returned an unsupported sign-in URL.')
    return value


def _public(flow):
    return {"status":flow["status"],"user_code":flow["user_code"],"verification_uri":flow.get("verification_uri",""),
            "expires_at":flow["expires_at"],"username":flow.get("username",""),
            "message":flow.get("message",""),"retry_after":max(1,int(flow.get("next_poll",0)-time.time())+1)}


def start(identifier,owner):
    global FLOW,LAST_START
    owner=_owner(owner)
    with FLOW_LOCK:
        _expire()
        if FLOW:
            if not hmac.compare_digest(FLOW["owner"],owner):
                raise ValueError("A Microsoft connection is already open in another browser. Finish it or disconnect to cancel it.")
            return _public(FLOW)
        if time.time()-LAST_START<10:raise ValueError("Wait a few seconds before starting another Microsoft connection.")
        LAST_START=time.time()
        with storage_lock():generation=_metadata()["generation"]
        flow_id=secrets.token_hex(24)
        FLOW={"id":flow_id,"owner":owner,"status":"starting","user_code":"","expires_at":time.time()+900,
              "generation":generation,"client_id":identifier}
    try:
        cache=msal.SerializableTokenCache();application=_app(identifier,cache)
        device=application.initiate_device_flow(scopes=SCOPES)
        code=device.get("user_code")
        if not isinstance(code,str) or not re.fullmatch(r"[A-Za-z0-9-]{4,32}",code) or not device.get("device_code"):
            raise ValueError("Microsoft sign-in could not start. Check that the registration supports personal accounts and public client flows.")
        uri=verification_uri(device.get("verification_uri"))
        seconds=int(device.get("expires_in",900))
        if not 30<=seconds<=1800:raise ValueError("Microsoft returned an invalid sign-in expiry. Try again.")
        with FLOW_LOCK:
            if not FLOW or FLOW["id"]!=flow_id:raise ValueError("Microsoft connection was cancelled.")
            FLOW.update(status="pending",user_code=code,verification_uri=uri,expires_at=time.time()+seconds,
                        application=application,cache=cache,device=device,next_poll=time.time()+max(5,int(device.get("interval",5))))
            return _public(FLOW)
    except Exception:
        with FLOW_LOCK:
            if FLOW and FLOW["id"]==flow_id:FLOW=None
        raise ValueError("Microsoft sign-in could not start. Check the registration and network connection.") from None


def poll(identifier,owner):
    global FLOW
    owner=_owner(owner)
    with FLOW_LOCK:
        _expire()
        if not FLOW:return {"status":"idle"}
        if not hmac.compare_digest(FLOW["owner"],owner):
            return {"status":"other_browser"}
        if FLOW["client_id"]!=identifier:raise ValueError("The Microsoft client ID changed. Cancel and reconnect.")
        if FLOW["status"]!="pending" or time.time()<FLOW["next_poll"] or FLOW.get("polling"):
            return _public(FLOW)
        flow=FLOW;flow["polling"]=True
    try:
        result=flow["application"].acquire_token_by_device_flow(flow["device"],exit_condition=lambda _:True)
        with FLOW_LOCK:
            if FLOW is not flow:return {"status":"idle"}
            if "access_token" in result:
                scopes=result.get("scope","").lower().split()
                if not any(scope in ("mail.send","https://graph.microsoft.com/mail.send") for scope in scopes):
                    raise ValueError("Microsoft did not grant email sending permission. Cancel and connect again.")
                identity=_identity(flow["cache"],identifier,{})
                if not identity:raise ValueError("Microsoft did not return one usable mailbox identity. Cancel and reconnect.")
                flow.update(status="ready",username=identity["username"],identity=identity,message="Review the mailbox, then choose Use this account.")
            elif result.get("error") not in ("authorization_pending","slow_down"):
                flow.update(status="failed",message="Microsoft sign-in was declined, expired or unsuccessful. Cancel and try again.")
                flow.pop("cache",None);flow.pop("application",None);flow.pop("device",None)
            else:
                flow["next_poll"]=time.time()+max(5,int(flow["device"].get("interval",5)))
            return _public(flow)
    except ValueError:
        with FLOW_LOCK:
            if FLOW is flow:
                flow.update(status="failed",message="Microsoft sign-in could not be completed. Cancel and try again.")
                flow.pop("cache",None);flow.pop("application",None);flow.pop("device",None)
        raise ValueError("Microsoft sign-in did not return a usable mailbox with email sending permission. Cancel and reconnect.") from None
    except Exception:
        with FLOW_LOCK:
            if FLOW is not flow:return {"status":"idle"}
            flow["next_poll"]=time.time()+15
            return dict(_public(flow),message="Microsoft could not be reached. Retrying shortly.")
    finally:
        with FLOW_LOCK:flow["polling"]=False


def confirm(identifier,owner,username):
    global FLOW
    owner=_owner(owner)
    with FLOW_LOCK:
        _expire()
        if not FLOW or FLOW["status"]!="ready" or not hmac.compare_digest(FLOW["owner"],owner):
            raise ValueError("Complete Microsoft sign-in in this browser before confirming the mailbox.")
        flow=FLOW
        if flow["client_id"]!=identifier or username!=flow["username"]:
            raise ValueError("The connection details changed. Cancel and reconnect.")
        expected=os.getenv("MICROSOFT_SENDER","").strip()
        if expected and expected.casefold()!=username.casefold():
            raise ValueError("This mailbox does not match MICROSOFT_SENDER. Sign in to the configured mailbox, or update that container setting first.")
        with storage_lock():
            metadata=_metadata()
            if metadata["generation"]!=flow["generation"]:
                FLOW=None
                raise ValueError("The Microsoft connection changed elsewhere. Start again.")
            # Remove old selection before replacing credentials; a failed write fails closed.
            _set_metadata({"generation":metadata["generation"]+1,"client_id":identifier,"home_account_id":"disconnected"})
            flow["cache"].has_state_changed=True
            _save(flow["cache"])
            _set_metadata(dict(flow["identity"],client_id=identifier,generation=metadata["generation"]+1))
        FLOW=None
        return {"connected":True,"username":username}


def cancel(owner):
    global FLOW
    owner=_owner(owner)
    with FLOW_LOCK:
        if FLOW and not hmac.compare_digest(FLOW["owner"],owner):
            raise ValueError("Cancel this connection from the browser that started it.")
        FLOW=None
    return {"status":"idle"}


def disconnect():
    global FLOW
    with FLOW_LOCK:
        FLOW=None
        with storage_lock():
            metadata=_metadata()
            _set_metadata({"generation":metadata["generation"]+1,"home_account_id":"disconnected"})
            _cache_path().unlink(missing_ok=True)
    return {"connected":False}


def connect(identifier,output=print):
    """Keep the console command compatible with the same guarded connection flow."""
    owner=secrets.token_hex(32)
    info=start(identifier,owner)
    output("Open "+info["verification_uri"]+" and enter code "+info["user_code"]+".")
    while info["status"] in ("pending","starting"):
        time.sleep(min(30,info.get("retry_after",5)))
        info=poll(identifier,owner)
    if info["status"]!="ready":raise RuntimeError("Microsoft sign-in was not completed. Try again.")
    confirm(identifier,owner,info["username"])
    return info["username"]


class GraphRejected(RuntimeError):
    """Graph returned an HTTP response rejecting the request."""
    def __init__(self,message,status=None):
        super().__init__(message);self.status=status


class GraphNotConnected(RuntimeError):
    """No request was sent because Microsoft needs a new authorisation."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def send_mime(identifier,mime_bytes,timeout=20,diagnostics=None):
    import mail_diagnostics as metadata
    token=access_token(identifier)
    if not token:raise GraphNotConnected("Microsoft account needs reconnecting in Settings.")
    request=urllib.request.Request(GRAPH_SEND,data=base64.b64encode(mime_bytes),method="POST",
        headers={"Authorization":"Bearer "+token,"Content-Type":"text/plain"})
    if diagnostics is not None:
        client=metadata.safe_metadata(diagnostics).get('client_request_id')
        if client:
            request.add_header('client-request-id',client)
            request.add_header('return-client-request-id','true')
    def capture(code,headers):
        if diagnostics is None:return
        values={'protocol_code':code,'request_id':headers.get('request-id'),'client_request_id':headers.get('client-request-id')}
        retry=headers.get('Retry-After','')
        if isinstance(retry,str) and retry.isdigit() and len(retry)<=5:values['retry_after']=int(retry)
        diagnostics.update(metadata.safe_metadata(values))
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=timeout) as response:
            capture(response.status,response.headers)
            return response.status
    except urllib.error.HTTPError as error:
        capture(error.code,error.headers or {})
        raise GraphRejected("Microsoft Graph rejected the email request (HTTP %s)."%error.code,error.code) from None
