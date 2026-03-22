import requests

TOKEN = "EAAWR2qA8tQ4BQ14Ha8xHvgx1O7mzbZBwg4mZCCApTvHO0PKz3Hm5Haf61KURt4cq4XMBiqra4QkGg4TkEiRJWGoPZAYYtXZChnsf4udI1u9ye2zQsyrPuFBy4YB92z2dY6IY5NlSDStwiveYTORZAcM9eVHCui5OZBqZBX3BzRdXFlGpt8vkEvItR0aBlIb5QunvgZDZD"
PHONE_ID = "903465276193459"        # ton phone number ID
TO = "2291097095752"                # ton numéro WhatsApp, sans +

url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
}
payload = {
    "messaging_product": "whatsapp",
    "to": TO,
    "type": "text",
    "text": {
        "body": "Test KRD EXPRESS direct"
    },
}

r = requests.post(url, headers=headers, json=payload, timeout=10)
print(r.status_code)
print(r.text)
