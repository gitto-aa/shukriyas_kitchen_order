# v44 performance cleanup

- Lazy app/manager navigation so hidden sections no longer execute every rerun.
- Loads Supabase data only for the visible section.
- Caches invoice fetch/render work and clears caches after relevant updates.
- Removes unused statement PDF/dead helper code.
- Keeps all existing ordering, menu, payment, expense, and settings workflows.
