# Shukriya's Kitchen Order App - v20

This version keeps the existing public ordering, manager dashboard, announcements, payment tracking, and notifications, and redesigns generated PDF invoices to be compact.

## v20 invoice changes
- A5-like invoice width instead of full US Letter width.
- Page height automatically shrinks to fit the invoice content for small orders.
- Compact business/customer header.
- Clean itemized invoice table with minimal grid lines.
- Zero-value delivery, discount, and tax rows are hidden.
- Larger orders can still continue onto additional pages when needed.

No Supabase migration is required for v20. Replace `app.py` (or deploy the full project) and restart the Streamlit app.

## v22
- Aligns the manager Download invoice and Print invoice controls on the same horizontal baseline.
- Removes the embedded print component's default browser body margin and matches the native Streamlit button height.
