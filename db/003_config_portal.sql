-- Configuração do portal (logo, nome exibido). Uma linha só.
-- Migração aditiva: não altera nada que já existe.
create table if not exists config_portal (
  id           smallint primary key default 1,
  logo_url     text,
  logo_letra   text default 'F',
  nome_exibido text,
  atualizado_em timestamptz not null default now(),
  constraint config_portal_unica check (id = 1)
);

insert into config_portal (id, logo_letra) values (1, 'F')
on conflict (id) do nothing;
