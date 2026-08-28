# Shukriya's Kitchen Orders — v15

This version keeps all v14 functionality and replaces the public customer cart with a compact table.

## Customer cart
The cart now shows one row per item with:
- Item
- Quantity
- Unit price
- Line total
- Remove checkbox

Customers can mark one or more rows and press **Remove selected**.

No Supabase/database migration is required for v15.


## v18 manager notifications
- Manager dashboard now polls for new online orders every 5 seconds while it is open.
- A bell shows a red dot and pending count when `Online` orders are still in `New` status.
- Clicking the bell shows a compact list of pending online orders.
- The alert automatically clears as managers move orders from `New` to `Confirmed`, `Preparing`, etc.
- This is an in-app alert; it is not an iOS/Android push notification when the browser/app is closed.
