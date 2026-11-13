-- Cadastros feitos pela operação (provas, inscrições, notas, cavalos, ginetes…)
-- Uma linha por coleção, guardada como JSON. A base oficial NÃO fica aqui:
-- ela vive no site. Migração aditiva, não altera nada existente.
create table if not exists dados_app (
  chave         text primary key,
  valor         jsonb not null,
  atualizado_em timestamptz not null default now()
);
