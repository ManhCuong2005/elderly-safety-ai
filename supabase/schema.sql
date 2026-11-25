begin;

create table if not exists public.telegram_links (
    user_id uuid primary key references auth.users(id) on delete cascade,
    chat_id bigint not null unique check (chat_id > 0),
    label text not null check (char_length(label) <= 120)
);

create table if not exists public.fall_alerts (
    id uuid primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    occurred_at timestamptz not null,
    telegram_status text not null check (telegram_status in ('pending', 'unlinked', 'sent', 'error'))
);

create index if not exists fall_alerts_user_time on public.fall_alerts (user_id, occurred_at desc);

alter table public.telegram_links enable row level security;
alter table public.fall_alerts enable row level security;

revoke all on public.telegram_links, public.fall_alerts from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.telegram_links to service_role;
grant select, insert, update on public.fall_alerts to service_role;

commit;
