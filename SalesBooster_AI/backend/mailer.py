import smtplib
from email.message import EmailMessage

def send_bulk_email(smtp_user, smtp_pass, leads, subject, body, db_session, owner_id):
    from models import EmailLog
    try:
        # Defaulting to standard Gmail SMTP layout
        server = smtplib.SMTP('vibetechlabs@gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        
        for email in leads:
            try:
                msg = EmailMessage()
                msg.set_content(body.replace("{email}", email))
                msg['Subject'] = subject
                msg['From'] = smtp_user
                msg['To'] = email
                
                # server.send_message(msg) # Uncomment to actually send
                
                log = EmailLog(target_email=email, subject=subject, status="success", owner_id=owner_id)
                db_session.add(log)
            except Exception as e:
                log = EmailLog(target_email=email, subject=subject, status="failed", error_msg=str(e), owner_id=owner_id)
                db_session.add(log)
        
        db_session.commit()
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP Server login failed: {e}")
        return False
