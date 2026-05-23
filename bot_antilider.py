#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================
  BOT DE VENDAS — MÚLTIPLOS LIVROS & HOTMART
  Telegram + Mercado Pago Checkout Pro + Hotmart Links
=============================================================

Funcionalidades:
  • /start    → Menu com seleção de livros (Mercado Pago) e produtos Hotmart
  • /divulgar → Mensagens prontas (PT/EN) para divulgação
  • /grupos   → Lista de grupos públicos sobre liderança e negócios
  • Geração de link de pagamento via Checkout Pro
  • Webhook para confirmação de pagamento
  • Envio automático do PDF após pagamento aprovado

Dependências:
  pip install python-telegram-bot[webhooks] mercadopago

Autor: Manus AI
"""

import os
import json
import logging
import uuid
import asyncio
from pathlib import Path
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import mercadopago
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────

TELEGRAM_TOKEN = "8738278665:AAHlFTsZfaVMqDPyLByiNB_EG6EBIhGD20Q"
MERCADOPAGO_ACCESS_TOKEN = "APP_USR-4583982947872694-040719-2434778fb7385091dd755d15f4f67106-3322210976"

# Catálogo de livros (Mercado Pago / Entrega Automática)
BOOKS = {
    "antilider": {
        "title": "Anti-Líder",
        "price": 32.00,
        "currency": "BRL",
        "description": "E-book Anti-Líder — Transforme sua visão sobre liderança",
        "pdf_filename": "antilider.pdf",
        "emoji": "📖",
        "subtitle": "Português",
    },
    "omf_pt": {
        "title": "OMF (Over a Why Me?)",
        "price": 32.00,
        "currency": "BRL",
        "description": "E-book OMF — Descubra seu propósito",
        "pdf_filename": "omf.pdf",
        "emoji": "🌟",
        "subtitle": "Português",
    },
    "omf_en": {
        "title": "OMF — Over Frame Maturity Framework",
        "price": 84.00,
        "currency": "BRL",
        "description": "E-book OMF — Over Frame Maturity Framework (English)",
        "pdf_filename": "omf_english.pdf",
        "emoji": "🌍",
        "subtitle": "English ($14.00 USD)",
    },
}

# Produtos Hotmart
HOTMART_PRODUCTS = [
    {
        "title": "Anti-Líder",
        "url": "https://go.hotmart.com/S105107590Q",
        "emoji": "📘"
    },
    {
        "title": "Achieve Stability in Container Terminals",
        "url": "https://rviannav.hotmart.host/achieve-stability-and-increase-productivity-in-container-terminals-25bfecf2-b413-446b-ba7a-b3e895248aed",
        "emoji": "⚓"
    },
    {
        "title": "OMF - Estrutura da Maturidade Operacional (PT)",
        "url": "https://go.hotmart.com/Y105182407G",
        "emoji": "⚙️"
    },
    {
        "title": "OMF - Operational Maturity Framework (EN)",
        "url": "https://go.hotmart.com/S104955580K",
        "emoji": "🌐"
    }
]

# Porta do servidor webhook para receber notificações do Mercado Pago
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", 8443))
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", "")

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# MERCADO PAGO SDK
# ─────────────────────────────────────────────

mp_sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)

# ─────────────────────────────────────────────
# ARMAZENAMENTO EM MEMÓRIA
# ─────────────────────────────────────────────

pending_payments: dict[str, tuple[int, str]] = {}
telegram_app: Application | None = None

# ─────────────────────────────────────────────
# TEXTOS E MENSAGENS
# ─────────────────────────────────────────────

WELCOME_TEXT = (
    "📚 *Bem\\-vindo à nossa livraria digital\\!*\n\n"
    "Temos duas opções de compra disponíveis para você:\n\n"
    "📦 *1\\. Entrega Automática via Telegram \\(Mercado Pago\\)*\n"
    "Os livros abaixo são enviados em PDF diretamente aqui no chat logo após o pagamento:\n\n"
)

HOTMART_TEXT = (
    "\n\n🔗 *2\\. Produtos na Hotmart*\n"
    "Compre pela plataforma Hotmart e tenha acesso à área de membros exclusiva:\n"
)

PAYMENT_GENERATED_TEXT = (
    "✅ *Link de pagamento gerado com sucesso\\!*\n\n"
    "Clique no botão abaixo para realizar o pagamento "
    "via PIX ou cartão de crédito/débito\\.\n\n"
    "Após a confirmação do pagamento, o PDF será "
    "enviado automaticamente aqui no chat\\. 📩"
)

PAYMENT_APPROVED_TEXT_TEMPLATE = (
    "🎉 *Pagamento confirmado\\!*\n\n"
    "Muito obrigado pela sua compra\\! Aqui está o seu exemplar "
    "digital de *{book_title}*\\.\n\n"
    "Boa leitura\\! 📚"
)

GROUPS_TEXT = (
    "👥 *Grupos Públicos sobre Liderança, Gestão e Negócios*\n\n"
    "Abaixo estão alguns grupos do Telegram onde você pode "
    "interagir com outros profissionais e divulgar nossos livros:\n\n"
    "1\\. [Liderança e Gestão Brasil](https://t.me/liderancaegestao)\n"
    "2\\. [Empreendedores Digitais](https://t.me/empreendedoresdigitais)\n"
    "3\\. [Marketing e Negócios](https://t.me/marketingenegocios)\n"
    "4\\. [Desenvolvimento Pessoal](https://t.me/desenvolvimentopessoalbr)\n"
    "5\\. [Gestão de Pessoas](https://t.me/gestaodepessoasbr)\n"
    "6\\. [Startups Brasil](https://t.me/startupsbrasil)\n"
    "7\\. [Líderes do Futuro](https://t.me/lideresdofuturobr)\n"
    "8\\. [Negócios e Finanças](https://t.me/negociosefinancas)\n\n"
    "💡 _Dica: use o comando /divulgar para obter mensagens prontas para compartilhar nestes grupos\\!_"
)

DIVULGAR_TEXT = (
    "📢 *Sistema de Divulgação*\n\n"
    "Copie as mensagens abaixo e compartilhe em grupos de liderança, negócios ou gestão de terminais para ajudar a divulgar nossos produtos\\!\n\n"
    "🇧🇷 *Mensagem em Português:*\n"
    "```text\n"
    "🚀 Você quer transformar sua visão sobre liderança e melhorar a produtividade da sua equipe? Conheça o livro \"Anti-Líder\" e a metodologia OMF (Operational Maturity Framework)!\n\n"
    "📚 Adquira os e-books com entrega automática no Telegram ou acesse a versão completa na Hotmart.\n\n"
    "👉 Fale com o bot oficial para conhecer os produtos: @Rviannavbot\n"
    "```\n\n"
    "🇺🇸 *Mensagem em Inglês (English Message):*\n"
    "```text\n"
    "🚀 Do you want to transform your leadership vision and improve team productivity? Discover the \"Anti-Leader\" book and the OMF (Operational Maturity Framework) methodology!\n\n"
    "📚 Get the e-books with automatic delivery on Telegram or access the full version on Hotmart.\n\n"
    "👉 Talk to the official bot to check out the products: @Rviannavbot\n"
    "```\n\n"
    "Dica: Envie essas mensagens nos grupos listados no comando /grupos\\!"
)

# ─────────────────────────────────────────────
# HANDLERS DO TELEGRAM
# ─────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta o menu de livros disponíveis."""
    keyboard_buttons = [
        [
            InlineKeyboardButton(
                f"{BOOKS['antilider']['emoji']} Anti-Líder — R$ 32,00",
                callback_data="select_book|antilider",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{BOOKS['omf_pt']['emoji']} OMF (Português) — R$ 32,00",
                callback_data="select_book|omf_pt",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{BOOKS['omf_en']['emoji']} OMF (English) — R$ 84,00",
                callback_data="select_book|omf_en",
            ),
        ],
    ]
    
    # Adiciona os botões da Hotmart
    for product in HOTMART_PRODUCTS:
        keyboard_buttons.append([
            InlineKeyboardButton(
                f"{product['emoji']} Hotmart: {product['title']}",
                url=product['url']
            )
        ])

    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    
    full_text = WELCOME_TEXT + HOTMART_TEXT
    
    await update.message.reply_text(
        full_text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


async def cmd_grupos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a lista de grupos públicos."""
    await update.message.reply_text(GROUPS_TEXT, parse_mode="MarkdownV2", disable_web_page_preview=True)


async def cmd_divulgar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe as mensagens prontas para divulgação."""
    await update.message.reply_text(DIVULGAR_TEXT, parse_mode="MarkdownV2")


async def callback_select_book(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usuário seleciona um livro com entrega automática."""
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split("|", 1)
    if len(data_parts) < 2:
        return

    book_id = data_parts[1]
    if book_id not in BOOKS:
        await query.message.reply_text("❌ Livro não encontrado.")
        return

    book = BOOKS[book_id]
    price_display = f"R\\$ {book['price']:.2f}"
    if book_id == "omf_en":
        price_display = f"R\\$ {book['price']:.2f} \\($14\\.00 USD\\)"

    await query.message.reply_text(
        f"📖 Você selecionou: *{book['title']}*\n\n"
        f"Preço: {price_display}\n\n"
        "Clique no botão abaixo para prosseguir com o pagamento\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"💳 Pagar {price_display}", callback_data=f"comprar|{book_id}")]]
        ),
    )


async def callback_comprar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gera o link de pagamento do Mercado Pago Checkout Pro."""
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split("|", 1)
    if len(data_parts) < 2:
        return

    book_id = data_parts[1]
    if book_id not in BOOKS:
        await query.message.reply_text("❌ Livro não encontrado.")
        return

    book = BOOKS[book_id]
    chat_id = query.message.chat_id
    external_ref = f"{book_id}-{chat_id}-{uuid.uuid4().hex[:8]}"

    # Armazena a referência para vincular o pagamento ao chat e livro
    pending_payments[external_ref] = (chat_id, book_id)

    # Monta a preferência de pagamento
    preference_data = {
        "items": [
            {
                "title": book["title"],
                "quantity": 1,
                "unit_price": book["price"],
                "currency_id": book["currency"],
                "description": book["description"],
            }
        ],
        "external_reference": external_ref,
        "payment_methods": {
            "installments": 3,
        },
        "back_urls": {
            "success": "https://t.me/Rviannavbot",
            "failure": "https://t.me/Rviannavbot",
            "pending": "https://t.me/Rviannavbot",
        },
        "auto_return": "approved",
        "statement_descriptor": book["title"][:20].upper(),
    }

    if WEBHOOK_BASE_URL:
        preference_data["notification_url"] = f"{WEBHOOK_BASE_URL}/webhook"

    try:
        preference_response = mp_sdk.preference().create(preference_data)
        preference = preference_response.get("response", {})
        checkout_url = preference.get("init_point", "")

        if not checkout_url:
            logger.error("Falha ao criar preferência: %s", preference_response)
            await query.message.reply_text(
                "❌ Ocorreu um erro ao gerar o link de pagamento\\. "
                "Tente novamente mais tarde\\.",
                parse_mode="MarkdownV2",
            )
            return

        logger.info(
            "Preferência criada — ID: %s | Ref: %s | Livro: %s | Chat: %s",
            preference.get("id"),
            external_ref,
            book_id,
            chat_id,
        )

        price_display = f"R\\$ {book['price']:.2f}"
        if book_id == "omf_en":
            price_display = f"R\\$ {book['price']:.2f}"

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(f"💳 Pagar {price_display}", url=checkout_url)],
                [InlineKeyboardButton("🔄 Já paguei — verificar", callback_data=f"verificar|{external_ref}")],
            ]
        )
        await query.message.reply_text(
            PAYMENT_GENERATED_TEXT,
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
        )

    except Exception as exc:
        logger.exception("Erro ao criar preferência de pagamento")
        await query.message.reply_text(
            "❌ Erro inesperado ao processar sua compra\\. Tente novamente\\.",
            parse_mode="MarkdownV2",
        )


async def callback_verificar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verifica manualmente se o pagamento foi aprovado."""
    query = update.callback_query
    await query.answer("🔍 Verificando pagamento...")

    data_parts = query.data.split("|", 1)
    if len(data_parts) < 2:
        return

    external_ref = data_parts[1]
    chat_id = query.message.chat_id

    try:
        filters = {"external_reference": external_ref}
        search_response = mp_sdk.payment().search(filters)
        results = search_response.get("response", {}).get("results", [])

        approved = any(p.get("status") == "approved" for p in results)

        if approved and external_ref in pending_payments:
            chat_id_stored, book_id = pending_payments.pop(external_ref)
            await send_book(chat_id_stored, book_id, context)
        else:
            await query.message.reply_text(
                "⏳ *Pagamento ainda não confirmado\\.*\n\n"
                "Se você já pagou via PIX, aguarde alguns instantes "
                "e clique novamente em *\"Já paguei — verificar\"*\\.\n\n"
                "Pagamentos com cartão podem levar até 1 minuto\\.",
                parse_mode="MarkdownV2",
            )

    except Exception as exc:
        logger.exception("Erro ao verificar pagamento")
        await query.message.reply_text(
            "❌ Erro ao verificar o pagamento\\. Tente novamente em instantes\\.",
            parse_mode="MarkdownV2",
        )


async def send_book(chat_id: int, book_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia o PDF do livro para o comprador."""
    if book_id not in BOOKS:
        logger.error("Livro não encontrado: %s", book_id)
        return

    book = BOOKS[book_id]
    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), book["pdf_filename"])

    try:
        with open(pdf_path, "rb") as pdf_file:
            payment_text = PAYMENT_APPROVED_TEXT_TEMPLATE.format(book_title=book["title"])
            await context.bot.send_message(
                chat_id=chat_id,
                text=payment_text,
                parse_mode="MarkdownV2",
            )
            await context.bot.send_document(
                chat_id=chat_id,
                document=pdf_file,
                filename=f"{book['title']}.pdf",
                caption=f"📖 {book['title']} — Seu exemplar digital",
            )
        logger.info("Livro %s enviado com sucesso para chat_id=%s", book_id, chat_id)
    except FileNotFoundError:
        logger.error("Arquivo PDF não encontrado: %s", pdf_path)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Desculpe, houve um erro ao enviar o livro. "
                 f"Por favor, entre em contato com o suporte.",
        )
    except Exception as exc:
        logger.exception("Erro ao enviar o livro para chat_id=%s", chat_id)


async def send_book_via_app(chat_id: int, book_id: str) -> None:
    """Envia o livro usando a instância global do Application (chamado pelo webhook)."""
    if telegram_app is None:
        logger.error("Application do Telegram não inicializado.")
        return

    if book_id not in BOOKS:
        logger.error("Livro não encontrado: %s", book_id)
        return

    book = BOOKS[book_id]
    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), book["pdf_filename"])

    try:
        bot = telegram_app.bot
        payment_text = PAYMENT_APPROVED_TEXT_TEMPLATE.format(book_title=book["title"])
        with open(pdf_path, "rb") as pdf_file:
            await bot.send_message(
                chat_id=chat_id,
                text=payment_text,
                parse_mode="MarkdownV2",
            )
            await bot.send_document(
                chat_id=chat_id,
                document=pdf_file,
                filename=f"{book['title']}.pdf",
                caption=f"📖 {book['title']} — Seu exemplar digital",
            )
        logger.info("Livro %s enviado via webhook para chat_id=%s", book_id, chat_id)
    except FileNotFoundError:
        logger.error("Arquivo PDF não encontrado: %s", pdf_path)
    except Exception as exc:
        logger.exception("Erro ao enviar livro via webhook para chat_id=%s", chat_id)


# ─────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roteia os callbacks dos botões inline."""
    query = update.callback_query
    data = query.data

    if data.startswith("select_book|"):
        await callback_select_book(update, context)
    elif data.startswith("comprar|"):
        await callback_comprar(update, context)
    elif data.startswith("verificar|"):
        await callback_verificar(update, context)


# ─────────────────────────────────────────────
# SERVIDOR WEBHOOK PARA MERCADO PAGO
# ─────────────────────────────────────────────


class MercadoPagoWebhookHandler(BaseHTTPRequestHandler):
    """Recebe notificações do Mercado Pago via HTTP POST."""

    def do_GET(self):
        """Responde a health checks."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Multi-Livros Webhook OK")

    def do_POST(self):
        """Processa notificações de pagamento do Mercado Pago."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body) if body else {}

            logger.info("Webhook recebido: %s", json.dumps(data, indent=2))

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

            action = data.get("action", "")
            topic = data.get("topic", "")
            data_id = data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else None

            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if not data_id and "id" in qs:
                data_id = qs["id"][0]
            if not topic and "topic" in qs:
                topic = qs["topic"][0]

            if action == "payment.updated" or topic in ("payment", "merchant_order"):
                if data_id:
                    self._process_payment(str(data_id), topic)

        except Exception as exc:
            logger.exception("Erro no webhook")
            self.send_response(500)
            self.end_headers()

    def _process_payment(self, resource_id: str, topic: str):
        """Verifica o pagamento e envia o livro se aprovado."""
        try:
            if topic == "merchant_order":
                order_response = mp_sdk.merchant_order().get(resource_id)
                order = order_response.get("response", {})
                payments = order.get("payments", [])
                external_ref = order.get("external_reference", "")

                approved = any(p.get("status") == "approved" for p in payments)
            else:
                payment_response = mp_sdk.payment().get(resource_id)
                payment = payment_response.get("response", {})
                status = payment.get("status", "")
                external_ref = payment.get("external_reference", "")
                approved = status == "approved"

            if approved and external_ref in pending_payments:
                chat_id, book_id = pending_payments.pop(external_ref)
                logger.info(
                    "Pagamento aprovado — Ref: %s | Livro: %s | Chat: %s",
                    external_ref,
                    book_id,
                    chat_id,
                )
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(send_book_via_app(chat_id, book_id))
                loop.close()

        except Exception as exc:
            logger.exception("Erro ao processar pagamento %s", resource_id)

    def log_message(self, format, *args):
        """Redireciona logs do HTTP server para o logger."""
        logger.info("Webhook HTTP: %s", format % args)


def start_webhook_server():
    """Inicia o servidor HTTP para receber webhooks do Mercado Pago."""
    server = HTTPServer(("0.0.0.0", WEBHOOK_PORT), MercadoPagoWebhookHandler)
    logger.info("Servidor webhook iniciado na porta %s", WEBHOOK_PORT)
    server.serve_forever()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────


def main():
    """Inicializa e executa o bot."""
    global telegram_app

    logger.info("=" * 50)
    logger.info("  BOT MULTI-LIVROS & HOTMART — Iniciando...")
    logger.info("=" * 50)

    for book_id, book in BOOKS.items():
        pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), book["pdf_filename"])
        if not Path(pdf_path).is_file():
            logger.error("ERRO: Arquivo PDF não encontrado em %s", pdf_path)
            logger.error("Coloque o arquivo '%s' na mesma pasta do bot.", book["pdf_filename"])
            return

    logger.info("✅ Todos os PDFs encontrados:")
    for book_id, book in BOOKS.items():
        logger.info("   • %s (%s) — R$ %.2f", book["title"], book["pdf_filename"], book["price"])

    if WEBHOOK_BASE_URL:
        logger.info("Webhook configurado: %s/webhook", WEBHOOK_BASE_URL)
    else:
        logger.info(
            "WEBHOOK_BASE_URL não configurada. "
            "O bot funcionará com verificação manual (botão 'Já paguei')."
        )

    webhook_thread = Thread(target=start_webhook_server, daemon=True)
    webhook_thread.start()

    telegram_app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    telegram_app.add_handler(CommandHandler("start", cmd_start))
    telegram_app.add_handler(CommandHandler("grupos", cmd_grupos))
    telegram_app.add_handler(CommandHandler("divulgar", cmd_divulgar))
    telegram_app.add_handler(CallbackQueryHandler(callback_router))

    logger.info("Bot rodando via polling. Pressione Ctrl+C para parar.")
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
