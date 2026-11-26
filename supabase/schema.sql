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

alter table public.fall_alerts add column if not exists source text not null default 'camera';

alter table public.fall_alerts drop constraint if exists fall_alerts_source_check;
alter table public.fall_alerts add constraint fall_alerts_source_check
    check (source in ('camera', 'video_test', 'camera_absence'));

alter table public.fall_alerts add column if not exists photo_jpeg bytea
    check (octet_length(photo_jpeg) <= 500000);

alter table public.fall_alerts add column if not exists has_photo boolean
    generated always as (photo_jpeg is not null) stored;

create index if not exists fall_alerts_user_time on public.fall_alerts (user_id, occurred_at desc);

create table if not exists public.camera_settings (
    user_id uuid primary key references auth.users(id) on delete cascade,
    absence_enabled boolean not null default false,
    absence_seconds integer not null default 60 check (absence_seconds between 10 and 3600)
);

alter table public.telegram_links enable row level security;
alter table public.fall_alerts enable row level security;
alter table public.camera_settings enable row level security;

revoke all on public.telegram_links, public.fall_alerts, public.camera_settings from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.telegram_links to service_role;
grant select, insert, update on public.fall_alerts to service_role;
grant select, insert, update on public.camera_settings to service_role;

notify pgrst, 'reload schema';

commit;
