"""
Scheduled BIS debt-table email.

Run by .github/workflows/bis-email.yml on a daily cron. It checks the BIS Data
Portal for the latest available quarter; if that quarter is newer than the one
we last emailed (recorded in bis_state.json), it renders the comparison table
as an HTML email and sends it via Gmail SMTP to everyone in BIS_EMAIL_RECIPIENTS.
Because BIS publishes quarterly, the daily check is a no-op on all but ~4 days
a year — recipients only ever get fresh numbers, never duplicates.

Environment variables (set as GitHub Actions repo secrets):
  GMAIL_ADDRESS         The sending Gmail account, e.g. "globaldebtbrief@gmail.com"
  GMAIL_APP_PASSWORD    A 16-char Google App Password for that account
                        (Google Account → Security → 2-Step Verification → App passwords)
  BIS_EMAIL_FROM        Optional display name, e.g. "Global Debt <globaldebtbrief@gmail.com>".
                        Defaults to the GMAIL_ADDRESS if unset.
  BIS_EMAIL_RECIPIENTS  Comma-separated recipient addresses
  FORCE_SEND            Optional; "1" to send even if no new quarter (for testing)

Recipients are BCC'd so they never see each other's addresses — no database,
no subscriber accounts needed.
"""
import json
import os
import smtplib
import sys
from email.message import EmailMessage

from bis_debt import build_table

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bis_state.json")


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _render_html(table):
    """A clean light-themed HTML table mirroring the printed BIS report.

    Inline styles only — email clients strip <style> blocks. Rising debt is
    shown in red, falling debt in green, matching the on-site page.
    """
    def _pct(v):
        return "&mdash;" if v is None else f"{v}%"

    def _chg(v):
        if v is None:
            return ("&mdash;", "#444")
        color = "#c0392b" if v > 0 else "#1e8449" if v < 0 else "#444"
        return (f"{'+' if v > 0 else ''}{v}%", color)

    cell = ("padding:8px 14px;border:1px solid #c8ccd4;font-size:14px;"
            "font-family:Georgia,'Times New Roman',serif;")
    th = ("padding:8px 14px;border:1px solid #c8ccd4;font-size:13px;color:#333;"
          "font-family:Georgia,'Times New Roman',serif;background:#eef0f3;")

    def _row(r):
        chg_txt, chg_color = _chg(r["change"])
        return (
            f'<tr>'
            f'<td style="{cell}text-align:left;color:#111;">{r["name"]}</td>'
            f'<td style="{cell}text-align:right;color:#111;">{_pct(r["baseline"])}</td>'
            f'<td style="{cell}text-align:right;color:#111;font-weight:bold;">{_pct(r["latest"])}</td>'
            f'<td style="{cell}text-align:right;color:{chg_color};">{chg_txt}</td>'
            f'</tr>'
        )

    spacer = '<tr><td colspan="4" style="padding:5px;border:none;"></td></tr>'
    body_rows = spacer.join("".join(_row(r) for r in grp) for grp in table["groups"])

    return f"""\
<div style="font-family:Georgia,'Times New Roman',serif;color:#111;max-width:640px;">
  <h2 style="font-size:18px;margin:0 0 4px;">BIS Total Non-Financial Debt-to-GDP &mdash; Pre &amp; Post Covid</h2>
  <p style="font-size:13px;color:#555;margin:0 0 16px;">
    Total credit to the non-financial sector (public + private), % of GDP &middot;
    pre-COVID ({table['baseline_label']}) vs latest quarter ({table['latest_label']}).
  </p>
  <table style="border-collapse:collapse;">
    <thead>
      <tr>
        <th style="{th}text-align:left;"></th>
        <th style="{th}text-align:right;">{table['baseline_label']}</th>
        <th style="{th}text-align:right;">{table['latest_label']}</th>
        <th style="{th}text-align:right;">Changes as % of GDP</th>
      </tr>
    </thead>
    <tbody>{body_rows}</tbody>
  </table>
  <p style="font-size:11px;color:#888;margin-top:14px;">Source: {table['source']}.</p>
  <p style="font-size:11px;color:#aaa;margin-top:6px;">
    Sent automatically when BIS publishes a new quarter.
  </p>
</div>"""


def _send(subject, html_body, gmail_address, app_password, sender, recipients):
    """Send one HTML email via Gmail SMTP, BCC'ing every recipient."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = sender              # visible To = the sender itself
    msg["Bcc"] = ", ".join(recipients)
    msg.set_content("This email is best viewed in an HTML-capable mail client.")
    msg.add_alternative(html_body, subtype="html")
    # Gmail app passwords are often shown with spaces; strip them.
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_address, app_password.replace(" ", ""))
        smtp.send_message(msg)


def main():
    table = build_table()
    latest = table["latest_period"]
    if not latest:
        print("No BIS data fetched (latest_period is null); aborting without sending.")
        sys.exit(1)

    force = os.getenv("FORCE_SEND") == "1"
    state = _load_state()
    if state.get("last_emailed_period") == latest and not force:
        print(f"No new quarter — latest={latest} already emailed. Nothing to do.")
        return

    try:
        gmail_address = os.environ["GMAIL_ADDRESS"]
        app_password = os.environ["GMAIL_APP_PASSWORD"]
        recipients = [e.strip() for e in os.environ["BIS_EMAIL_RECIPIENTS"].split(",")
                      if e.strip()]
    except KeyError as e:
        print(f"Missing required environment variable: {e}. Aborting.")
        sys.exit(1)

    sender = os.getenv("BIS_EMAIL_FROM") or gmail_address

    if not recipients:
        print("BIS_EMAIL_RECIPIENTS is empty; nothing to send.")
        sys.exit(1)

    subject = f"BIS Total Non-Financial Debt-to-GDP — {table['latest_label']} update"
    _send(subject, _render_html(table), gmail_address, app_password, sender, recipients)
    print(f"Sent {table['latest_label']} update to {len(recipients)} recipient(s) "
          f"from {sender}.")

    state["last_emailed_period"] = latest
    _save_state(state)


if __name__ == "__main__":
    main()
