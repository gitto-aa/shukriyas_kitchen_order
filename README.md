# Home Kitchen Invoice App — Supabase Version

A small multi-user Streamlit web app for taking home-kitchen orders, using Supabase as the central database for menu prices, order history, and invoice line items.

## What this version does

- Stores menu items and prices in Supabase instead of Excel/OneDrive.
- Lets multiple people take orders from phones, tablets, or computers.
- Keeps each user's in-progress cart separate in their Streamlit session.
- Re-checks the current database price when an order is submitted.
- Saves every order and its line items centrally.
- Generates unique sequential invoice numbers such as `HK-000001`.
- Generates PDF invoices and lets you re-download recent invoices.
- Shows recent order history.
- Supports delivery fee, discount, tax, customer details, notes, payment status, and order status fields.
- Provides an optional shared app password.

## 1. Create a Supabase project

Create a free project at Supabase.

After the project is ready, open **SQL Editor**, create a new query, paste the entire contents of `database.sql`, and run it once.

That creates:

- `menu`
- `orders`
- `order_items`
- the transactional `create_kitchen_order(...)` database function
- a unique invoice-number sequence
- four starter menu items

## 2. Edit your menu

In Supabase, go to **Table Editor → menu**.

The important columns are:

| Column | Meaning |
|---|---|
| `dish` | Dish name |
| `category` | Main, Side, Dessert, etc. |
| `price` | Current unit price |
| `available` | `true` shows it in the app; `false` hides it |

You can change a price or availability at any time. The Streamlit app refreshes menu data every 30 seconds, and users can also press **Refresh menu**.

## 3. Add your Supabase credentials

Copy:

`.streamlit/secrets.example.toml`

to:

`.streamlit/secrets.toml`

Then fill in your project values:

```toml
BUSINESS_NAME = "My Home Kitchen"
BUSINESS_PHONE = "(555) 555-5555"
BUSINESS_ADDRESS = "Davis, CA"
CURRENCY = "$"
APP_TIMEZONE = "America/Los_Angeles"
APP_PASSWORD = "your-shared-app-password"

[supabase]
url = "https://YOUR_PROJECT.supabase.co"
service_role_key = "YOUR_SUPABASE_SERVICE_ROLE_KEY"
```

You can find the project URL and API keys in the Supabase project settings.

### Security

The `service_role_key` must remain server-side. Do **not** put it directly inside `app.py` and do **not** commit `.streamlit/secrets.toml` to GitHub. The included `.gitignore` already excludes that file.

The SQL script enables Row Level Security without creating browser-access policies. The Streamlit server accesses the database using the service-role credential stored in Streamlit Secrets.

## 4. Run locally

Install Python 3.10+ and run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 5. Deploy on Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload `app.py`, `database.sql`, `requirements.txt`, `.gitignore`, `.streamlit/secrets.example.toml`, and `README.md`.
3. Do **not** upload `.streamlit/secrets.toml`.
4. Create a Streamlit Community Cloud app from the repository.
5. Set `app.py` as the main file.
6. Open the app's Secrets settings and paste the contents of your local `.streamlit/secrets.toml`.
7. Deploy.

## Database behavior

When a user presses **Save & generate invoice**, the app sends only each menu item ID and quantity to the `create_kitchen_order` function. Supabase then:

1. checks that every menu item is still available;
2. reads the current menu price directly from the database;
3. creates a unique invoice number;
4. saves an immutable price snapshot in `order_items`;
5. calculates subtotal, discount, tax, and total on the server;
6. saves the complete order transactionally.

This is safer than trusting the price displayed earlier in a user's browser session.

## Current limitations / good next upgrades

- The app uses one optional shared password rather than individual employee accounts.
- Menu editing is done through Supabase Table Editor rather than inside the app.
- Order/payment statuses are stored but are not yet editable from the Streamlit interface.

Good next upgrades would be individual logins, an in-app menu editor for administrators, status buttons (`New → Cooking → Ready → Delivered`), payment status updates, and daily/monthly sales dashboards.
