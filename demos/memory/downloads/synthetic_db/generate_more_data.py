#!/usr/bin/env python3
"""
Append synthetic banking data to reach target volumes:
  customers    → 200+ (currently 20, adding 180)
  accounts     → 200+ (currently 30, adding 175)
  transactions → 1000+ (currently 70, adding 950)

Run from the same directory as the CSV files.
"""

import csv
import io
import random
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(42)
DATA_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Reference pools
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "James","Mary","John","Patricia","Robert","Jennifer","Michael","Linda",
    "William","Barbara","David","Susan","Richard","Jessica","Joseph","Sarah",
    "Thomas","Karen","Charles","Lisa","Christopher","Nancy","Daniel","Betty",
    "Matthew","Margaret","Anthony","Sandra","Mark","Ashley","Donald","Dorothy",
    "Steven","Kimberly","Paul","Emily","Andrew","Donna","Joshua","Michelle",
    "Kevin","Carol","Brian","Amanda","George","Melissa","Timothy","Deborah",
    "Ronald","Stephanie","Edward","Rebecca","Jason","Sharon","Jeffrey","Laura",
    "Ryan","Cynthia","Jacob","Kathleen","Gary","Amy","Nicholas","Angela",
    "Eric","Shirley","Jonathan","Anna","Stephen","Brenda","Larry","Pamela",
    "Justin","Emma","Scott","Nicole","Brandon","Helen","Benjamin","Samantha",
    "Samuel","Katherine","Raymond","Christine","Gregory","Debra","Frank","Rachel",
    "Alexander","Carolyn","Patrick","Janet","Jack","Catherine","Dennis","Maria",
    "Jerry","Heather","Tyler","Diane","Aaron","Julie","Jose","Joyce","Adam",
    "Victoria","Henry","Kelly","Nathan","Christina","Douglas","Lauren","Zachary",
    "Joan","Peter","Evelyn","Kyle","Olivia","Walter","Judith","Ethan","Megan",
    "Jeremy","Cheryl","Harold","Martha","Terry","Andrea","Sean","Frances",
    "Christian","Hannah","Carlos","Jacqueline","Arthur","Ann","Dylan","Gloria",
    "Louis","Teresa","Joe","Kathryn","Alan","Sara","Juan","Janice","Willie",
    "Jean","Austin","Alice","Wayne","Madison","Roy","Doris","Jesse","Abigail",
    "Jordan","Julia","Bryan","Judy","Billy","Grace","Bruce","Denise",
    "Liang","Wei","Yuki","Kenji","Priya","Arjun","Fatima","Omar","Elena",
    "Diego","Valentina","Marco","Giulia","Ivan","Olga","Tariq","Amina",
]

LAST_NAMES = [
    "Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis",
    "Rodriguez","Martinez","Hernandez","Lopez","Gonzalez","Wilson","Anderson",
    "Thomas","Taylor","Moore","Jackson","Martin","Lee","Perez","Thompson",
    "White","Harris","Sanchez","Clark","Ramirez","Lewis","Robinson","Walker",
    "Young","Allen","King","Wright","Scott","Torres","Nguyen","Hill","Flores",
    "Green","Adams","Nelson","Baker","Hall","Rivera","Campbell","Mitchell",
    "Carter","Roberts","Gomez","Phillips","Evans","Turner","Diaz","Parker",
    "Cruz","Edwards","Collins","Reyes","Stewart","Morris","Morales","Murphy",
    "Cook","Rogers","Gutierrez","Ortiz","Morgan","Cooper","Peterson","Bailey",
    "Reed","Kelly","Howard","Ramos","Kim","Cox","Ward","Richardson","Watson",
    "Brooks","Chavez","Wood","James","Bennett","Gray","Mendoza","Ruiz",
    "Hughes","Price","Alvarez","Castillo","Sanders","Patel","Myers","Long",
    "Ross","Foster","Jimenez","Powell","Jenkins","Perry","Russell","Sullivan",
    "Bell","Coleman","Butler","Henderson","Barnes","Gonzales","Fisher","Vasquez",
    "Chen","Zhang","Wang","Li","Liu","Yang","Tanaka","Suzuki","Sato","Kumar",
    "Singh","Sharma","Müller","Schmidt","Weber","Fischer","Meyer","Wagner",
]

CITIES = [
    ("New York","NY","10001"),("Los Angeles","CA","90001"),("Chicago","IL","60601"),
    ("Houston","TX","77001"),("Phoenix","AZ","85001"),("Philadelphia","PA","19101"),
    ("San Antonio","TX","78201"),("San Diego","CA","92101"),("Dallas","TX","75201"),
    ("San Jose","CA","95101"),("Austin","TX","78701"),("Jacksonville","FL","32099"),
    ("Fort Worth","TX","76101"),("Columbus","OH","43085"),("Charlotte","NC","28201"),
    ("Indianapolis","IN","46201"),("San Francisco","CA","94102"),("Seattle","WA","98101"),
    ("Denver","CO","80201"),("Nashville","TN","37201"),("Oklahoma City","OK","73101"),
    ("El Paso","TX","79901"),("Boston","MA","02101"),("Portland","OR","97201"),
    ("Las Vegas","NV","89101"),("Memphis","TN","38101"),("Louisville","KY","40201"),
    ("Baltimore","MD","21201"),("Milwaukee","WI","53201"),("Albuquerque","NM","87101"),
    ("Tucson","AZ","85701"),("Fresno","CA","93650"),("Sacramento","CA","95814"),
    ("Mesa","AZ","85201"),("Atlanta","GA","30301"),("Omaha","NE","68101"),
    ("Colorado Springs","CO","80901"),("Raleigh","NC","27601"),("Miami","FL","33101"),
    ("Minneapolis","MN","55401"),("Cleveland","OH","44101"),("Tampa","FL","33601"),
    ("New Orleans","LA","70112"),("Honolulu","HI","96801"),("Anchorage","AK","99501"),
]

STREETS = [
    "Main St","Oak Ave","Maple Rd","Cedar Blvd","Pine St","Elm Dr","Walnut Ln",
    "Washington Blvd","Lincoln Ave","Jefferson St","Madison Dr","Adams Rd",
    "Park Ave","Lake Dr","River Rd","Hill St","Forest Ave","Valley Blvd",
    "Sunset Dr","Sunrise Ave","Meadow Ln","Garden St","Spring Rd","Summer Ave",
    "Highland Dr","Westwood Blvd","Eastside Ave","Northgate Rd","Southview Dr",
]

LANGUAGES = ["EN","EN","EN","EN","EN","ES","ES","FR","DE","ZH","JA","AR","PT","HI"]
SEGMENTS  = ["RETAIL","RETAIL","RETAIL","RETAIL","PREMIUM","BUSINESS","STUDENT"]
KYC       = ["VERIFIED","VERIFIED","VERIFIED","VERIFIED","PENDING","RESTRICTED"]

ACCOUNT_TYPES = ["CHECKING","SAVINGS","CHECKING","CHECKING","SAVINGS","CREDIT","MONEY_MARKET"]
ACCOUNT_STATUS = ["ACTIVE","ACTIVE","ACTIVE","ACTIVE","ACTIVE","FROZEN","LOCKED"]

MERCHANTS = [
    ("Amazon","ONLINE_RETAIL"),("Walmart","GROCERY"),("Target","RETAIL"),
    ("Whole Foods Market","GROCERY"),("Costco","GROCERY"),("Apple Store","ELECTRONICS"),
    ("Best Buy","ELECTRONICS"),("Home Depot","HOME_IMPROVEMENT"),("Netflix","SUBSCRIPTION"),
    ("Spotify","SUBSCRIPTION"),("Uber","TRANSPORT"),("Lyft","TRANSPORT"),
    ("DoorDash","FOOD_DELIVERY"),("Grubhub","FOOD_DELIVERY"),("Shell","GAS"),
    ("BP","GAS"),("Chevron","GAS"),("Starbucks","CAFE"),("McDonald's","RESTAURANT"),
    ("Chipotle","RESTAURANT"),("CVS Pharmacy","HEALTH"),("Walgreens","HEALTH"),
    ("Chase Bank ATM","ATM"),("PG&E","UTILITIES"),("Comcast","UTILITIES"),
    ("AT&T","TELECOM"),("Verizon","TELECOM"),("LA Fitness","FITNESS"),
    ("Planet Fitness","FITNESS"),("Airbnb","TRAVEL"),("Delta Airlines","TRAVEL"),
    ("United Airlines","TRAVEL"),("Hilton Hotels","TRAVEL"),("Marriott","TRAVEL"),
    ("Nordstrom","RETAIL"),("H&M","RETAIL"),("Zara","RETAIL"),
    ("Digital Bank Loans","FINANCIAL_SERVICES"),("Venmo","TRANSFER"),("Zelle","TRANSFER"),
]

TXN_CHANNELS = ["POS","ONLINE","ATM","MOBILE","SYSTEM"]
TXN_TYPES    = ["DEBIT","DEBIT","DEBIT","DEBIT","CREDIT","PAYMENT","WIRE","TRANSFER"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def rand_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))

def rand_masked() -> str:
    return f"****{random.randint(1000,9999)}"

def fmt_date(d) -> str:
    return d.strftime("%Y-%m-%d") if d else ""

def fmt_ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else ""

def rand_ts(start: datetime, end: datetime) -> datetime:
    delta = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, delta))


# ---------------------------------------------------------------------------
# Generate customers
# ---------------------------------------------------------------------------
def gen_customers(start_idx: int, count: int) -> list:
    rows = []
    used_emails = set()
    for i in range(count):
        n = start_idx + i
        first = random.choice(FIRST_NAMES)
        last  = random.choice(LAST_NAMES)
        email_base = f"{first.lower()}.{last.lower()}{random.randint(1,999)}@email.com"
        while email_base in used_emails:
            email_base = f"{first.lower()}.{last.lower()}{random.randint(1,9999)}@email.com"
        used_emails.add(email_base)

        city, state, zip_code = random.choice(CITIES)
        street_num = random.randint(100, 9999)
        street = random.choice(STREETS)

        dob = rand_date(date(1950,1,1), date(2003,12,31))
        reg = rand_date(date(2010,1,1), date(2025,6,30))
        kyc = random.choice(KYC)
        lang = random.choice(LANGUAGES)
        seg  = random.choice(SEGMENTS)

        rows.append({
            "customer_id": f"CUST-B{n:03d}",
            "full_name": f"{first} {last}",
            "email": email_base,
            "phone": f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}",
            "date_of_birth": fmt_date(dob),
            "address": f'"{street_num} {street}, {city} {state} {zip_code}"',
            "kyc_status": kyc,
            "registration_date": fmt_date(reg),
            "preferred_language": lang,
            "customer_segment": seg,
            "notes": "",
        })
    return rows


# ---------------------------------------------------------------------------
# Generate accounts (1-2 per customer)
# ---------------------------------------------------------------------------
def gen_accounts(customers: list, start_acc_idx: int, target: int) -> list:
    rows = []
    acc_idx = start_acc_idx
    cust_queue = list(customers)
    random.shuffle(cust_queue)

    # Give every customer at least 1 account
    for cust in cust_queue:
        cid = cust["customer_id"]
        acc_type = random.choice(ACCOUNT_TYPES)
        status = random.choices(
            ACCOUNT_STATUS,
            weights=[70, 10, 10, 10, 5, 3, 2],
            k=1
        )[0]
        lock_reason = ""
        if status == "FROZEN":
            lock_reason = random.choice(["SUSPICIOUS_ACTIVITY","KYC_REVIEW","FRAUD_ALERT"])
        elif status == "LOCKED":
            lock_reason = random.choice(["FAILED_LOGINS","CUSTOMER_REQUEST","SECURITY_HOLD"])

        opened = rand_date(date(2015,1,1), date(2025,1,1))
        last_act = rand_date(opened, date(2026,4,30))

        if acc_type == "CREDIT":
            limit = round(random.uniform(1000,25000),2)
            bal = round(random.uniform(0, limit * 0.6), 2)
            avail = round(limit - bal, 2)
            rate = round(random.uniform(15.99, 26.99), 2)
            overdraft = 0.00
            daily_limit = 0.00
        elif acc_type in ("SAVINGS","MONEY_MARKET"):
            bal = round(random.uniform(500, 150000), 2)
            avail = bal
            rate = round(random.uniform(0.5, 5.0), 2)
            limit = 0.00
            overdraft = 0.00
            daily_limit = round(random.uniform(500, 5000), 2)
        else:  # CHECKING
            bal = round(random.uniform(200, 50000), 2)
            avail = round(bal * random.uniform(0.85, 1.0), 2)
            rate = 0.05
            limit = 0.00
            overdraft = round(random.choice([0, 200, 500, 1000]), 2)
            daily_limit = round(random.choice([1000, 2000, 5000, 10000]), 2)

        rows.append({
            "account_id": f"ACC-{100000 + acc_idx}",
            "customer_id": cid,
            "account_type": acc_type,
            "account_number_masked": rand_masked(),
            "currency": "USD",
            "current_balance": f"{bal:.2f}",
            "available_balance": f"{avail:.2f}",
            "status": status,
            "lock_reason": lock_reason,
            "opened_date": fmt_date(opened),
            "last_activity_date": fmt_date(last_act),
            "interest_rate_pct": f"{rate:.2f}",
            "overdraft_limit": f"{overdraft:.2f}",
            "daily_transfer_limit": f"{daily_limit:.2f}",
            "notes": "",
        })
        acc_idx += 1

        if acc_idx - start_acc_idx >= target:
            break

    # If still below target, add second accounts to some customers
    random.shuffle(cust_queue)
    for cust in cust_queue:
        if acc_idx - start_acc_idx >= target:
            break
        cid = cust["customer_id"]
        acc_type = "SAVINGS" if random.random() > 0.4 else "CHECKING"
        opened = rand_date(date(2018,1,1), date(2025,6,1))
        last_act = rand_date(opened, date(2026,4,30))
        bal = round(random.uniform(100, 30000), 2)
        rows.append({
            "account_id": f"ACC-{100000 + acc_idx}",
            "customer_id": cid,
            "account_type": acc_type,
            "account_number_masked": rand_masked(),
            "currency": "USD",
            "current_balance": f"{bal:.2f}",
            "available_balance": f"{bal:.2f}",
            "status": "ACTIVE",
            "lock_reason": "",
            "opened_date": fmt_date(opened),
            "last_activity_date": fmt_date(last_act),
            "interest_rate_pct": "0.05" if acc_type == "CHECKING" else f"{round(random.uniform(0.5,4.5),2):.2f}",
            "overdraft_limit": "0.00",
            "daily_transfer_limit": "2000.00",
            "notes": "",
        })
        acc_idx += 1

    return rows


# ---------------------------------------------------------------------------
# Generate transactions (~5-7 per account)
# ---------------------------------------------------------------------------
def gen_transactions(accounts: list, start_txn_idx: int, target: int) -> list:
    rows = []
    txn_idx = start_txn_idx
    ts_start = datetime(2025, 6, 1)
    ts_end   = datetime(2026, 4, 30)

    for acc in accounts:
        if txn_idx - start_txn_idx >= target:
            break
        cid = acc["customer_id"]
        aid = acc["account_id"]
        bal = float(acc["current_balance"])
        n_txns = random.randint(4, 9)

        for _ in range(n_txns):
            if txn_idx - start_txn_idx >= target:
                break
            merchant, cat = random.choice(MERCHANTS)
            txn_type = random.choice(TXN_TYPES)
            amount = round(random.uniform(5, 2000), 2)

            if txn_type == "CREDIT":
                bal = round(bal + amount, 2)
                bal_after = bal
            else:
                bal_after = round(max(0, bal - amount), 2)
                bal = bal_after

            initiated = rand_ts(ts_start, ts_end)
            completed = initiated + timedelta(minutes=random.randint(0, 60)) if random.random() > 0.1 else None

            status = random.choices(
                ["COMPLETED","PENDING","FAILED"],
                weights=[70, 15, 15],
                k=1
            )[0]
            failure = ""
            if status == "FAILED":
                failure = random.choice(["INSUFFICIENT_FUNDS","ACCOUNT_FROZEN","LIMIT_EXCEEDED","CARD_DECLINED"])
                completed = None

            rows.append({
                "transaction_id": f"TXN-2026-{txn_idx:06d}",
                "account_id": aid,
                "customer_id": cid,
                "transaction_type": txn_type,
                "amount": f"{amount:.2f}",
                "currency": "USD",
                "balance_after": f"{bal_after:.2f}",
                "merchant_name": merchant,
                "merchant_category": cat,
                "description": f"{txn_type.capitalize()} at {merchant}",
                "status": status,
                "initiated_at": fmt_ts(initiated),
                "completed_at": fmt_ts(completed) if completed else "",
                "channel": random.choice(TXN_CHANNELS),
                "reference_number": f"REF-{uuid.uuid4().hex[:8].upper()}",
                "failure_reason": failure,
                "notes": "",
            })
            txn_idx += 1

    return rows


# ---------------------------------------------------------------------------
# Append to CSV
# ---------------------------------------------------------------------------
def append_csv(path: Path, rows: list):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in rows:
            writer.writerow(row)
    print(f"  ✓ Appended {len(rows)} rows → {path.name}")


# ---------------------------------------------------------------------------
# Sarah Williams (CUST-B007) demo timeline
# ---------------------------------------------------------------------------
# Pin the account-lock scenario to the presentation timeline (freeze on
# 2026-05-14, follow-up 2026-05-18). These are base seed records (not appended
# above), so the patch rewrites the matching rows in place and is idempotent.
SARAH_PATCHES = [
    ("customers.csv", "customer_id", "CUST-B007", {
        "notes": "Checking account frozen on 2026-05-14 after 5 consecutive failed login attempts. Security hold in place.",
    }),
    ("accounts.csv", "account_id", "ACC-100013", {
        "last_activity_date": "2026-05-14",
        "notes": "Frozen on 2026-05-14 after 5 consecutive failed login attempts. Security hold pending identity verification. Case CASE-2026-0002.",
    }),
    ("cards.csv", "card_id", "CARD-000010", {
        "last_used_date": "2026-05-13",
        "notes": "Blocked automatically when account ACC-100013 was frozen for suspicious activity on 2026-05-14.",
    }),
    ("transactions.csv", "transaction_id", "TXN-2026-000025", {
        "initiated_at": "2026-05-13 16:45:00",
        "completed_at": "2026-05-13 16:45:00",
    }),
    ("transactions.csv", "transaction_id", "TXN-2026-000026", {
        "initiated_at": "2026-05-14 06:00:00",
        "notes": "Account frozen at 04:33 on 2026-05-14 after 5 failed login attempts. All transactions blocked.",
    }),
    ("support_cases.csv", "case_id", "CASE-2026-0002", {
        "created_at": "2026-05-14 05:00:00",
        "updated_at": "2026-05-18 11:00:00",
        "notes": "Account ACC-100013 frozen after 5 failed login attempts at 04:33 on 2026-05-14. Customer contacted by email. Awaiting government ID verification to unfreeze. Card CARD-000010 also blocked.",
    }),
]


def patch_sarah_records():
    """Rewrite Sarah Williams' base rows in place with the demo-timeline dates.

    Only the matched rows are re-serialised (found by their leading ID, which is
    column 0 in every affected file); all other lines are left byte-for-byte
    untouched, so the pre-existing ragged base rows are not disturbed.
    Idempotent: re-running sets the same values.
    """
    by_file = {}
    for fname, id_col, id_val, fields in SARAH_PATCHES:
        by_file.setdefault(fname, []).append((id_col, id_val, fields))

    for fname, patches in by_file.items():
        path = DATA_DIR / fname
        with open(path, newline="", encoding="utf-8") as f:
            lines = f.readlines()
        header = next(csv.reader([lines[0]]))
        col_idx = {name: i for i, name in enumerate(header)}

        applied = 0
        for idx in range(1, len(lines)):
            for id_col, id_val, fields in patches:
                if not lines[idx].startswith(id_val + ","):
                    continue
                row = next(csv.reader([lines[idx]]))
                if row[col_idx[id_col]] != id_val:
                    continue
                for col, val in fields.items():
                    row[col_idx[col]] = val
                buf = io.StringIO()
                csv.writer(buf, lineterminator="\n").writerow(row)
                lines[idx] = buf.getvalue()
                applied += 1

        with open(path, "w", newline="", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"  ✓ Patched {applied} Sarah Williams record(s) → {fname}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Generating additional synthetic banking data")
    print("=" * 60)

    # Targets: 180 new customers, 175 new accounts, 950 new transactions
    NEW_CUSTOMERS   = 180
    NEW_ACCOUNTS    = 175
    NEW_TRANSACTIONS = 950

    print(f"\nGenerating {NEW_CUSTOMERS} customers (CUST-B021 → CUST-B{20+NEW_CUSTOMERS:03d})...")
    customers = gen_customers(start_idx=21, count=NEW_CUSTOMERS)
    append_csv(DATA_DIR / "customers.csv", customers)

    print(f"\nGenerating {NEW_ACCOUNTS} accounts (ACC-100031 → ...)...")
    accounts = gen_accounts(customers, start_acc_idx=31, target=NEW_ACCOUNTS)
    append_csv(DATA_DIR / "accounts.csv", accounts)

    print(f"\nGenerating {NEW_TRANSACTIONS} transactions (TXN-2026-000071 → ...)...")
    transactions = gen_transactions(accounts, start_txn_idx=71, target=NEW_TRANSACTIONS)
    append_csv(DATA_DIR / "transactions.csv", transactions)

    print("\nPatching Sarah Williams (CUST-B007) demo timeline...")
    patch_sarah_records()

    # Verify
    print("\n" + "=" * 60)
    print("Final row counts")
    print("=" * 60)
    for fname in ["customers","accounts","transactions","loans","cards","support_cases"]:
        path = DATA_DIR / f"{fname}.csv"
        count = sum(1 for _ in open(path)) - 1
        print(f"  {fname:<15}: {count} rows")


if __name__ == "__main__":
    main()
