-- ============================================================================
-- Portal Freio do Proprietário — esquema do banco
--
-- REGRAS DESTE ARQUIVO (valem para toda migração futura):
--   1. Só ACRESCENTA. Nunca renomeia, nunca troca tipo, nunca apaga coluna.
--      Campo que não se usa mais é marcado como obsoleto, não removido.
--   2. Cada mudança é um arquivo numerado em migrations/ que roda UMA vez.
--   3. Dado oficial (importado da ABCCC) fica separado do dado digitado.
--   4. Toda linha diz de onde veio: fonte, selo, criado_em, atualizado_em.
--   5. A tela lê views (vw_*), não as tabelas cruas.
--
-- Postgres puro: nada de extensão proprietária em uso. Migrar de provedor é
-- pg_dump + pg_restore.
-- ============================================================================

create table if not exists schema_version (
  versao      integer      primary key,
  arquivo     text         not null,
  checksum    text,
  aplicada_em timestamptz  not null default now()
);

-- ---------------------------------------------------------------- ciclo
create table if not exists ciclo (
  id            text primary key,
  nome          text not null,
  inicio        date,
  fim           date,
  disponivel    boolean not null default true,
  documento     text,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

-- ---------------------------------------------------------------- categoria
create table if not exists categoria (
  id        text primary key,
  nome      text not null,
  grupo     char(1) not null check (grupo in ('A','B')),
  idade     text,
  ordem     smallint not null default 0
);

-- ---------------------------------------------------------------- animal
create table if not exists animal (
  id                 bigint generated always as identity primary key,
  nome               text not null,
  nome_norm          text not null,
  registro           text,
  rg                 text,
  sexo               text,
  pelagem            text,
  nascimento         date,
  criador            text,
  afixo              text,
  proprietario       text,
  expositor          text,
  estabelecimento    text,
  domador            text,
  pai_nome           text,
  mae_nome           text,
  -- acrescentados depois, sempre com default: nunca bloqueiam insert antigo
  observacao         text,
  foto_url           text,
  fonte              text,
  selo               text not null default 'informado'
                     check (selo in ('oficial','informado','semfonte')),
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz not null default now()
);
create unique index if not exists ux_animal_norm on animal (nome_norm);

-- ---------------------------------------------------------------- pessoa
create table if not exists pessoa (
  id                 bigint generated always as identity primary key,
  nome               text not null,
  nome_norm          text not null,
  profissao          text,
  cidade             text,
  uf                 char(2),
  nascimento         date,
  bio                text,
  foto_url           text,
  verificado         boolean not null default false,
  fonte              text,
  selo               text not null default 'informado'
                     check (selo in ('oficial','informado','semfonte')),
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz not null default now()
);
create unique index if not exists ux_pessoa_norm on pessoa (nome_norm);

-- grafias diferentes da mesma pessoa (não apaga, só registra)
create table if not exists pessoa_grafia (
  id        bigint generated always as identity primary key,
  pessoa_id bigint not null references pessoa(id) on delete cascade,
  grafia    text not null,
  criado_em timestamptz not null default now()
);
create unique index if not exists ux_pessoa_grafia on pessoa_grafia (pessoa_id, grafia);

-- ---------------------------------------------------------------- evento
create table if not exists evento (
  id             bigint generated always as identity primary key,
  chave          text unique,          -- identificador estável vindo do app
  nome           text not null,
  tipo           text not null check (tipo in ('credenciadora','ranking','final')),
  ciclo_id       text references ciclo(id),
  cidade         text,
  uf             char(2),
  local          text,
  data_inicio    date,
  data_fim       date,
  tecnico        text,
  status         text not null default 'publicado',
  documento      text,
  versao         integer not null default 1,
  fonte          text,
  selo           text not null default 'oficial',
  criado_em      timestamptz not null default now(),
  atualizado_em  timestamptz not null default now()
);

-- ---------------------------------------------------------------- inscrição
create table if not exists inscricao (
  id            bigint generated always as identity primary key,
  evento_id     bigint not null references evento(id) on delete cascade,
  ciclo_id      text references ciclo(id),
  categoria_id  text not null references categoria(id),
  animal_id     bigint not null references animal(id),
  pessoa_id     bigint references pessoa(id),
  box           integer,
  status        text not null default 'inscrito',
  fonte         text,
  selo          text not null default 'oficial',
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);
create index if not exists ix_inscricao_evento on inscricao (evento_id, categoria_id);
create unique index if not exists ux_inscricao_unica
  on inscricao (evento_id, categoria_id, animal_id);

-- ---------------------------------------------------------------- resultado
create table if not exists resultado (
  id               bigint generated always as identity primary key,
  inscricao_id     bigint not null references inscricao(id) on delete cascade,
  evento_id        bigint not null references evento(id) on delete cascade,
  ciclo_id         text references ciclo(id),
  categoria_id     text not null references categoria(id),
  posicao          integer,
  posicao_oficial  integer,
  media            numeric(6,3),
  soma             numeric(8,3),
  pontos           integer,
  pontos_oficiais  integer,
  habilitado       boolean,
  concluiu         boolean,
  origem           text not null default 'credenciadora',
  fonte            text,
  selo             text not null default 'oficial',
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now()
);
create unique index if not exists ux_resultado_inscricao on resultado (inscricao_id);
create index if not exists ix_resultado_ciclo on resultado (ciclo_id, categoria_id);

-- nota de cada etapa (a súmula detalhada)
create table if not exists nota_etapa (
  id            bigint generated always as identity primary key,
  resultado_id  bigint not null references resultado(id) on delete cascade,
  etapa         text not null,
  jurado_1      numeric(5,2),
  jurado_2      numeric(5,2),
  media         numeric(6,3),
  penalidade    numeric(5,2) not null default 0,
  criado_em     timestamptz not null default now()
);
create index if not exists ix_nota_resultado on nota_etapa (resultado_id);

-- ---------------------------------------------------------------- final
create table if not exists final (
  id                 bigint generated always as identity primary key,
  ciclo_id           text not null references ciclo(id),
  nome               text not null,
  local              text,
  data_inicio        date,
  data_fim           date,
  conjuntos_inscritos integer,
  tem_classificacao  boolean not null default false,
  documento          text,
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz not null default now()
);
create unique index if not exists ux_final_ciclo on final (ciclo_id);

-- ---------------------------------------------------------------- calendário
create table if not exists calendario_prova (
  id        bigint generated always as identity primary key,
  cidade    text not null,
  data      date not null,
  tipo      text not null default 'credenciadora',
  ciclo_id  text references ciclo(id),
  fonte     text,
  criado_em timestamptz not null default now()
);
create unique index if not exists ux_calendario on calendario_prova (cidade, data);

-- ---------------------------------------------------------------- usuários
create table if not exists usuario (
  id            bigint generated always as identity primary key,
  nome          text not null,
  email         text not null,
  senha_hash    text not null,
  papel         text not null default 'leitor'
                check (papel in ('leitor','editor','admin','superadmin')),
  ativo         boolean not null default true,
  criado_em     timestamptz not null default now(),
  ultimo_acesso timestamptz
);
create unique index if not exists ux_usuario_email on usuario (lower(email));

create table if not exists sessao (
  token      text primary key,
  usuario_id bigint not null references usuario(id) on delete cascade,
  criado_em  timestamptz not null default now(),
  expira_em  timestamptz not null
);

-- ---------------------------------------------------------------- banners
create table if not exists banner (
  id           bigint generated always as identity primary key,
  titulo       text not null,
  texto        text,
  link         text,
  imagem_url   text,
  cor          text,
  posicao      text not null check (posicao in ('topo','listas','lateral','rodape')),
  inicio       date,
  fim          date,
  ativo        boolean not null default true,
  impressoes   bigint not null default 0,
  cliques      bigint not null default 0,
  criado_em    timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

-- ---------------------------------------------------------------- analytics
create table if not exists visita_dia (
  dia      date not null,
  pagina   text not null,
  visitas  integer not null default 0,
  primary key (dia, pagina)
);

create table if not exists busca_log (
  id        bigint generated always as identity primary key,
  termo     text not null,
  dia       date not null default current_date
);

-- ---------------------------------------------------------------- importação
create table if not exists importacao (
  id           bigint generated always as identity primary key,
  arquivo      text not null,
  formato      text,
  linhas       integer not null default 0,
  criados      integer not null default 0,
  atualizados  integer not null default 0,
  rejeitados   integer not null default 0,
  status       text not null default 'publicada',
  usuario_id   bigint references usuario(id),
  evento_id    bigint references evento(id),
  detalhe      jsonb,
  criado_em    timestamptz not null default now()
);

-- ---------------------------------------------------------------- auditoria
create table if not exists auditoria (
  id           bigint generated always as identity primary key,
  quando       timestamptz not null default now(),
  usuario_id   bigint references usuario(id),
  usuario_nome text,
  acao         text not null,
  entidade     text not null,
  entidade_id  text,
  anterior     jsonb,
  novo         jsonb,
  motivo       text,
  fonte        text
);
create index if not exists ix_auditoria_quando on auditoria (quando desc);
