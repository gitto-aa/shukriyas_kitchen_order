# Shukriya's Kitchen Invoice App v23

Manager-side revision:

- Kitchen address is now saved from **Manager > Settings** and printed on invoices.
- Staff orders include an optional **Customer code / short name**.
- Order History can search invoice number, customer name, short code, or phone.
- Downloaded invoice filenames include the customer code when present, e.g. `HK-000023_ADIB.pdf`.
- Staff orders include scrollable **Delivery date** and **Delivery time** selectors.
- Delivery date/time can be edited later from Order History.
- Delivery date/time are printed prominently in **bold** on PDF and direct-print invoices.

Supabase schema has already been updated for the connected project.
