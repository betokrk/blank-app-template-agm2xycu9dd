# Publicar o Portal Freio — passo a passo

Você está na tela **Projects** do Railway. Esta é a ordem exata.

---

## 1. Suba o código no GitHub (5 minutos, uma vez)

O Railway publica a partir de um repositório. Escolha um:

**Opção A — pelo site (mais fácil)**
1. Entre em **github.com**, crie um repositório novo chamado `portal-freio`, **privado**.
2. Clique em **uploading an existing file**.
3. Arraste **todos** os arquivos deste pacote (menos a pasta `__pycache__`, se houver).
4. **Commit changes**.

**Opção B — pelo terminal, se preferir**
```bash
sudo apt install git        # só se não tiver
git init
git add .
git commit -m "portal freio"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/portal-freio.git
git push -u origin main
```

> **Atenção:** nunca suba o arquivo `.env` com senhas. Ele não está aqui, e não deve entrar.

---

## 2. Crie o projeto no Railway

1. Na tela **Projects**, clique em **+ New**.
2. Escolha **Deploy from GitHub repo**.
3. Autorize o Railway a ver seu GitHub (só na primeira vez).
4. Selecione `portal-freio`.

O Railway começa a instalar. **Vai falhar no primeiro momento** — está sem banco. É esperado.

---

## 3. Adicione o banco

1. No projeto, clique em **+ New** (no canto do projeto, não dentro do serviço).
2. Escolha **Database** → **PostgreSQL**.
3. Espere o cartão do Postgres ficar verde.

O Railway cria a variável `DATABASE_URL` sozinho e a entrega para a aplicação. Você não precisa copiar nada.

---

## 4. Configure o administrador

1. Clique no serviço da **aplicação** (o que tem o nome do repositório).
2. Aba **Variables** → **+ New Variable**, três vezes:

| Nome | Valor |
|---|---|
| `ADMIN_EMAIL` | seu e-mail |
| `ADMIN_SENHA` | uma senha forte, sua escolha |
| `ADMIN_NOME` | Roberto Amaral |

3. **Deploy** (ou o serviço reinicia sozinho).

### O que acontece agora, sozinho

Ao subir, o app faz tudo isto sem você pedir:

- cria as 20 tabelas;
- aplica as views;
- carrega 804 animais, 452 pessoas, 1.247 inscrições, 1.130 resultados e 27 provas do calendário;
- cria o seu usuário administrador com a senha que você pôs;
- cria 4 banners de demonstração.

Leva cerca de **um a dois minutos** no primeiro boot. Se o site abrir vazio, espere e recarregue.

---

## 5. Pegue o endereço

Aba **Settings** → **Networking** → **Generate Domain**.

Fica algo como `portal-freio-production.up.railway.app`. Esse é o site, já no ar.

Depois, quando quiser, apontamos um domínio próprio para ele — o passo é o mesmo de antes, só troca o endereço.

---

## Como conferir que funcionou

Abra a raiz do endereço. A home deve mostrar:

- os chips de ciclo 2025 / 2026 / 2027;
- **495 conjuntos, 383 habilitados, 484 cavalos, 332 ginetes** no ciclo 2026.

E `SEU-ENDERECO/api/saude` deve responder:

```json
{"ok": true, "animais": 804, "versao_banco": 2}
```

Se `animais` estiver zerado, a importação ainda está rodando — aguarde e recarregue.

---

## Se algo der errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Site 502 / não abre | app caiu no boot | aba **Deployments** → veja os logs, procure `[inicio]` |
| `ok: false` na saúde | banco indisponível | confirme que o Postgres está no mesmo projeto |
| Home sem números | importação em andamento ou falhou | recarregue; se persistir, veja os logs |
| Esqueci a senha | — | troque `ADMIN_SENHA` e faça **Redeploy** (só define se não houver admin) |

Para redefinir a senha depois, com o admin já existente, use no seu computador:
```bash
python3 scripts/criar_admin.py "Roberto Amaral" seu@email.com "nova-senha"
```

---

## Custo

**US$ 5/mês** (Railway Hobby), cobrado no cartão. Cobre site e banco no mesmo lugar, sempre no ar, sem pausa.

---

## O que fica para a próxima etapa

- **Login do site publicado**: a API já autentica e autoriza; falta a tela do HTML conversar com ela. Hoje o admin do site publicado grava no navegador.
- **OCR e PDF no servidor**: imagem e PDF escaneado precisam de leitura no servidor, onde a chave pode ficar escondida.
