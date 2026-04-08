# Bot de Vendas "Anti-Líder"

Este é um bot completo para Telegram em Python que vende o livro digital "Anti-Líder" e envia o PDF automaticamente após a confirmação do pagamento via Mercado Pago Checkout Pro.

## Funcionalidades

- `/start`: Apresenta o livro e exibe o botão de compra.
- `/grupos`: Exibe uma lista de grupos públicos do Telegram para divulgação.
- **Integração Mercado Pago**: Gera link de pagamento dinâmico de R$ 32,00.
- **Confirmação Dupla**: O bot verifica pagamentos automaticamente via Webhook e permite que o usuário verifique manualmente clicando em "Já paguei — verificar".
- **Entrega Automática**: O arquivo PDF é enviado diretamente no chat após o pagamento ser aprovado.

## Pré-requisitos

Para rodar este bot em um servidor (VPS, nuvem ou local), você precisará de:

1. Python 3.8 ou superior instalado.
2. O arquivo do livro (`antilider.pdf`) na mesma pasta do script.
3. Conexão com a internet para acessar a API do Telegram e do Mercado Pago.

## Como Executar

### Passo 1: Instalar Dependências

Abra o terminal na pasta do projeto e instale as bibliotecas necessárias executando o comando abaixo:

```bash
pip install -r requirements.txt
```

### Passo 2: Configurar o Webhook (Opcional, mas recomendado)

O bot inicia um servidor HTTP na porta `8443` para receber notificações do Mercado Pago em tempo real. 
Para que isso funcione, o Mercado Pago precisa conseguir acessar o seu servidor pela internet.

Se você tiver um domínio ou IP público, exporte a variável de ambiente `WEBHOOK_BASE_URL` antes de iniciar o bot:

```bash
export WEBHOOK_BASE_URL="https://seu-dominio-ou-ip.com:8443"
```

*Nota: Se você não configurar o webhook, o bot ainda funcionará perfeitamente. O usuário só precisará clicar no botão "Já paguei — verificar" após realizar o pagamento.*

### Passo 3: Iniciar o Bot

Para rodar o bot no terminal, execute:

```bash
python3 bot_antilider.py
```

### Executando em Produção (Segundo Plano)

Para manter o bot rodando mesmo após fechar o terminal, você pode usar o `nohup` ou o `screen`:

```bash
nohup python3 bot_antilider.py > bot.log 2>&1 &
```

Ou, idealmente, crie um serviço no `systemd` (Linux) para que o bot inicie automaticamente com o servidor.

## Arquivos do Projeto

- `bot_antilider.py`: O código fonte principal do bot.
- `requirements.txt`: Lista de dependências Python.
- `antilider.pdf`: O arquivo do e-book (deve estar presente na mesma pasta).
- `README.md`: Este arquivo de instruções.
