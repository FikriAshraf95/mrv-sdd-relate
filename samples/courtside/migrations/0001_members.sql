-- SPEC-02 members
create table members (
    id uuid primary key,
    email text not null unique,
    name text not null,
    role text not null check (role in ('member', 'desk', 'admin')),
    created_at timestamptz not null
);
