"""Demo users created by `iip seed`. Only ever advertised by the API when DEMO_MODE=true."""

DEMO_ACCOUNTS: list[dict[str, str]] = [
    {"email": "clerk@acme.test", "password": "clerk-demo-pass", "role": "clerk", "name": "Riya Sharma"},
    {"email": "approver@acme.test", "password": "approver-demo-pass", "role": "approver", "name": "Arjun Mehta"},
    {"email": "admin@acme.test", "password": "admin-demo-pass", "role": "admin", "name": "Kavya Iyer"},
]
