-- ============================================================================
-- Views — é o que a API entrega e o que a tela consome.
-- A tela NUNCA lê tabela crua: assim eu reorganizo tabela por baixo sem
-- quebrar contrato nenhum com o front.
-- ============================================================================

-- ranking por ciclo e categoria, com posição como publicada
create or replace view vw_ranking as
select
  r.ciclo_id                as ciclo,
  r.categoria_id            as categoria,
  c.nome                    as categoria_nome,
  c.grupo                   as grupo,
  r.posicao,
  r.posicao_oficial,
  r.pontos,
  r.pontos_oficiais,
  r.media,
  r.habilitado,
  r.origem,
  r.selo,
  a.id                      as animal_id,
  a.nome                    as animal,
  a.registro,
  a.rg,
  a.sexo,
  a.pelagem,
  a.criador,
  a.expositor,
  a.estabelecimento,
  p.id                      as pessoa_id,
  p.nome                    as pessoa,
  i.box,
  e.nome                    as evento,
  e.documento
from resultado r
join inscricao i on i.id = r.inscricao_id
join animal    a on a.id = i.animal_id
left join pessoa p on p.id = i.pessoa_id
join categoria c on c.id = r.categoria_id
join evento    e on e.id = r.evento_id;

-- contagem por ciclo (o número que aparece na home)
create or replace view vw_ciclo_numeros as
select
  r.ciclo_id                                          as ciclo,
  count(*)                                            as conjuntos,
  count(*) filter (where r.habilitado)                as habilitados,
  count(distinct i.animal_id)                         as animais,
  count(distinct i.pessoa_id)                         as pessoas,
  count(distinct i.animal_id)
    filter (where r.origem = 'final')                 as animais_final
from resultado r
join inscricao i on i.id = r.inscricao_id
group by r.ciclo_id;

-- comparativo credenciadora x final (mesmo animal, mesmo ciclo)
create or replace view vw_comparativo_final as
select
  f.ciclo_id                as ciclo,
  f.categoria_id            as categoria,
  f.posicao                 as posicao_final,
  f.media                   as nota_final,
  f.selo                    as selo_final,
  cf.posicao                as posicao_credenciadora,
  cf.media                  as nota_credenciadora,
  a.id                      as animal_id,
  a.nome                    as animal,
  p.id                      as pessoa_final_id,
  p.nome                    as pessoa_final,
  pc.id                     as pessoa_credenciadora_id,
  pc.nome                   as pessoa_credenciadora,
  -- só é troca quando EXISTE ginete na credenciadora e é outra pessoa
  (pc.id is not null and p.id <> pc.id) as trocou_ginete
from resultado f
join inscricao i     on i.id = f.inscricao_id
join animal    a     on a.id = i.animal_id
left join pessoa p   on p.id = i.pessoa_id
left join resultado cf on cf.ciclo_id = f.ciclo_id
                      and cf.categoria_id = f.categoria_id
                      and cf.origem = 'credenciadora'
                      and cf.inscricao_id = (
                        select i2.id from inscricao i2
                        where i2.animal_id = i.animal_id
                          and i2.ciclo_id = f.ciclo_id
                          and i2.categoria_id = f.categoria_id
                          and i2.evento_id in (select e2.id from evento e2 where e2.tipo = 'ranking')
                        limit 1
                      )
left join inscricao ic on ic.id = cf.inscricao_id
left join pessoa pc    on pc.id = ic.pessoa_id
where f.origem = 'final';

-- cavalos que trocaram de ginete entre credenciadora e final
create or replace view vw_comercializados as
select distinct
  ciclo, categoria, animal_id, animal,
  pessoa_credenciadora, pessoa_final, posicao_final, nota_final
from vw_comparativo_final
where trocou_ginete = true;

-- pessoas com mais de um animal na final, por categoria
create or replace view vw_ginetes_multi as
select
  f.ciclo_id           as ciclo,
  f.categoria_id       as categoria,
  p.id                 as pessoa_id,
  p.nome               as pessoa,
  count(*)             as animais,
  array_agg(a.nome order by a.nome) as lista
from resultado f
join inscricao i on i.id = f.inscricao_id
join animal    a on a.id = i.animal_id
join pessoa    p on p.id = i.pessoa_id
where f.origem = 'final'
group by f.ciclo_id, f.categoria_id, p.id, p.nome
having count(*) > 1;

-- banners no ar hoje
create or replace view vw_banner_ativo as
select *
from banner
where ativo = true
  and (inicio is null or inicio <= current_date)
  and (fim    is null or fim    >= current_date)
order by posicao, id;

-- visitas somadas por página (últimos 30 dias)
create or replace view vw_analytics_pagina as
select pagina, sum(visitas) as visitas
from visita_dia
where dia >= current_date - interval '30 days'
group by pagina
order by visitas desc;
