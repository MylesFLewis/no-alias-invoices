# v0.29

Latest test invoices may be removed after a successful email send. The UI warns that deletion cannot recall the sent email. Removing the latest sent test invoice deletes its email-status record and PDF copy and rolls its counter back so the test number can be reused. Sending and uncertain invoices remain protected.
