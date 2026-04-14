#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================
  BOT DE VENDAS — MÚLTIPLOS LIVROS
  Telegram + Mercado Pago Checkout Pro
=============================================================

Funcionalidades:
  • /start  → Menu com seleção de livros disponíveis
  • /grupos → Lista de grupos públicos sobre liderança
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

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
MERCADOPAGO_ACCESS_TOKEN = os.environ["MERCADOPAGO_ACCESS_TOKEN"]

# URLs da Amazon (configuráveis via variáveis de ambiente)
AMAZON_URL_ANTILIDER = os.environ.get("AMAZON_URL_ANTILIDER", "")
AMAZON_URL_OMF_PT    = os.environ.get("AMAZON_URL_OMF_PT", "")
AMAZON_URL_OMF_EN    = os.environ.get("AMAZON_URL_OMF_EN", "")

# file_ids do Telegram para cada PDF (configurados via /getfileid)
# Quando definidos, o bot envia o arquivo pelo Telegram sem precisar do PDF no servidor.
# Configure as variáveis de ambiente BOOK_FILE_ID_ANTILIDER, BOOK_FILE_ID_OMF_PT e
# BOOK_FILE_ID_OMF_EN no Railway após rodar /getfileid.
BOOK_FILE_IDS: dict[str, str] = {
    "antilider": os.environ.get("BOOK_FILE_ID_ANTILIDER", ""),
    "omf_pt":    os.environ.get("BOOK_FILE_ID_OMF_PT", ""),
    "omf_en":    os.environ.get("BOOK_FILE_ID_OMF_EN", ""),
}

# ID do chat do administrador (para comandos restritos como /getfileid)
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

# Catálogo de livros
BOOKS = {
    "antilider": {
        "title": "Anti-Líder",
        "price": 32.00,
        "currency": "BRL",
        "description": "E-book Anti-Líder — Transforme sua visão sobre liderança",
        "pdf_filename": "antilider.pdf",
        "emoji": "📖",
        "subtitle": "Português",
        "amazon_url": AMAZON_URL_ANTILIDER,
    },
    "omf_pt": {
        "title": "OMF (Over a Why Me?)",
        "price": 32.00,
        "currency": "BRL",
        "description": "E-book OMF — Descobra seu propósito",
        "pdf_filename": "omf.pdf",
        "emoji": "🌟",
        "subtitle": "Português",
        "amazon_url": AMAZON_URL_OMF_PT,
    },
    "omf_en": {
        "title": "OMF — Over Frame Maturity Framework",
        "price": 84.00,
        "currency": "BRL",
        "description": "E-book OMF — Over Frame Maturity Framework (English)",
        "pdf_filename": "omf_english.pdf",
        "emoji": "🌍",
        "subtitle": "English ($14.00 USD)",
        "amazon_url": AMAZON_URL_OMF_EN,
    },
}

# Porta do servidor webhook para receber notificações do Mercado Pago
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", 8443))

# URL pública do webhook (deve ser configurada com seu domínio/IP público)
# Exemplo: https://seudominio.com:8443/webhook
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
# Mapeia external_reference → (chat_id, book_id)
# Em produção, use um banco de dados.
# ─────────────────────────────────────────────

pending_payments: dict[str, tuple[int, str]] = {}

# Contador de compras por livro (prova social — semente realista)
# Em produção, persista em banco de dados.
purchase_counts: dict[str, int] = {
    "antilider": 214,
    "omf_pt":    97,
    "omf_en":    38,
}

# Controle de promoção relâmpago
import time as _time

PROMO_ACTIVE: bool = False
PROMO_DISCOUNT_PCT: int = 30          # % de desconto da promoção
PROMO_DURATION_SECONDS: int = 3600   # 1 hora
PROMO_END_TIME: float = 0.0

# Referência global ao Application do Telegram (preenchida em main)
telegram_app: Application | None = None

# ─────────────────────────────────────────────
# TEXTOS E MENSAGENS
# ─────────────────────────────────────────────

WELCOME_TEXT = (
    "📚 *Bem\\-vindo à nossa livraria digital\\!*\n\n"
    "Junte\\-se a centenas de leitores que já transformaram "
    "sua visão de liderança e propósito com nossos e\\-books\\.\n\n"
    "🔥 *Escolha seu livro e comece agora:*\n\n"
    "🔹 *Anti\\-Líder* — Transforme sua visão sobre liderança \\(Português\\)\n"
    "🔹 *OMF \\(Over a Why Me\\?\\)* — Descubra seu propósito \\(Português\\)\n"
    "🔹 *OMF — Over Frame Maturity Framework* — English \\($14\\.00 USD\\)\n\n"
    "⚡ _Entrega imediata após o pagamento — direto aqui no chat\\!_"
)

PAYMENT_GENERATED_TEXT = (
    "✅ *Link de pagamento gerado\\!*\n\n"
    "⏳ *Atenção:* este link é válido por *30 minutos*\\. "
    "Finalize agora para garantir sua cópia\\!\n\n"
    "Aceitamos PIX \\(aprovação imediata\\) e cartão de crédito/débito\\.\n\n"
    "📩 O PDF será entregue *automaticamente* neste chat assim que "
    "o pagamento for confirmado\\."
)

PAYMENT_APPROVED_TEXT_TEMPLATE = (
    "🎉 *Pagamento confirmado\\!*\n\n"
    "Obrigado pela confiança\\! Você faz parte de um grupo seleto "
    "de leitores que escolheram crescer\\. 🚀\n\n"
    "Aqui está seu exemplar de *{book_title}*\\.\n\n"
    "💡 _Dica: compartilhe sua experiência com amigos — "
    "a transformação é ainda maior quando vivida em comunidade\\._"
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
    "💡 _Dica: compartilhe o link @Rviannavbot nos grupos "
    "para que mais pessoas conheçam nossos livros\\!_"
)

AMAZON_STRATEGY_TEXT = (
    "🛒 *Estratégia de Vendas na Amazon — KDP*\n\n"
    "Veja abaixo as principais práticas para maximizar as vendas "
    "dos seus livros na Amazon Kindle Direct Publishing \\(KDP\\):\n\n"
    "📝 *1\\. Título e Subtítulo com Palavras\\-Chave*\n"
    "Use termos que seu público pesquisa \\(ex: liderança, autoconhecimento, "
    "gestão\\) no título e subtítulo para aparecer nas buscas orgânicas\\.\n\n"
    "🖼 *2\\. Capa Profissional*\n"
    "A capa é o primeiro impacto\\. Invista em design que se destaque "
    "nas miniaturas da Amazon\\.\n\n"
    "⭐ *3\\. Avaliações \\(Reviews\\)*\n"
    "Peça para leitores avaliarem seu livro após a compra\\. "
    "Avaliações aumentam a credibilidade e o rankeamento\\.\n\n"
    "📣 *4\\. Amazon Ads \\(KDP Ads\\)*\n"
    "Crie campanhas de anúncios patrocinados dentro da própria Amazon "
    "com palavras\\-chave relacionadas ao seu nicho\\.\n\n"
    "🆓 *5\\. Kindle Select / KDP Select*\n"
    "Ao entrar no programa KDP Select, você pode oferecer dias gratuitos "
    "e participar do Kindle Unlimited, ampliando o alcance\\.\n\n"
    "📊 *6\\. Precificação Estratégica*\n"
    "Teste diferentes preços \\(promoções temporárias a R\\$9,90 geram "
    "volume e reviews; preço cheio sustenta margem\\)\\.\n\n"
    "🌐 *7\\. Tráfego Externo*\n"
    "Direcione seguidores das redes sociais, grupos do Telegram e e\\-mail "
    "marketing para a página do livro na Amazon\\.\n\n"
    "🔁 *8\\. Série de Livros*\n"
    "Livros em série têm desempenho superior: quem compra o primeiro "
    "tende a comprar os seguintes\\.\n\n"
    "─────────────────────────\n"
    "📚 *Nossos Livros na Amazon:*"
)

# ─────────────────────────────────────────────
# HANDLERS DO TELEGRAM
# ─────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta o menu de livros disponíveis."""
    keyboard = InlineKeyboardMarkup(
        [
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
    )
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


async def cmd_grupos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a lista de grupos públicos."""
    await update.message.reply_text(GROUPS_TEXT, parse_mode="MarkdownV2", disable_web_page_preview=True)


async def cmd_getfileid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando admin: envia cada PDF para o Telegram e retorna os file_ids.
    Use os file_ids para configurar as variáveis de ambiente no Railway.
    """
    chat_id = update.effective_chat.id
    if ADMIN_CHAT_ID and chat_id != ADMIN_CHAT_ID:
        return  # silenciosamente ignora não-admins

    await update.message.reply_text(
        "⏳ Enviando PDFs para o Telegram e capturando file\\_ids\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    lines = ["📋 *file\\_ids dos livros* — cole no Railway como variáveis de ambiente:\n"]
    for book_id, book in BOOKS.items():
        # Verifica se já tem file_id configurado
        existing = BOOK_FILE_IDS.get(book_id, "")
        if existing:
            lines.append(
                f"✅ *{book['title']}*\n"
                f"`BOOK_FILE_ID_{book_id.upper()}` já configurado\\."
            )
            continue

        pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), book["pdf_filename"])
        if not os.path.isfile(pdf_path):
            lines.append(
                f"❌ *{book['title']}*\n"
                f"Arquivo `{book['pdf_filename']}` não encontrado no servidor\\."
            )
            continue

        try:
            with open(pdf_path, "rb") as f:
                msg = await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=book["pdf_filename"],
                    caption=f"[upload interno] {book['title']}",
                )
            file_id = msg.document.file_id
            env_key = f"BOOK_FILE_ID_{book_id.upper()}"
            lines.append(
                f"📖 *{book['title']}*\n"
                f"`{env_key}` \\= `{file_id}`"
            )
        except Exception:
            logger.exception("Erro ao fazer upload do PDF %s", book_id)
            lines.append(f"❌ *{book['title']}* — erro no upload\\.")

    lines.append(
        "\n⚙️ _Copie cada valor acima e adicione em Railway → seu projeto → Variables\\._"
    )
    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode="MarkdownV2",
    )


async def cmd_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ativa uma promoção relâmpago de 1 hora com desconto em todos os livros."""
    global PROMO_ACTIVE, PROMO_END_TIME

    PROMO_ACTIVE = True
    PROMO_END_TIME = _time.time() + PROMO_DURATION_SECONDS

    mins = PROMO_DURATION_SECONDS // 60
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                f"{BOOKS['antilider']['emoji']} Anti-Líder — {PROMO_DISCOUNT_PCT}% OFF",
                callback_data="comprar_promo|antilider",
            )],
            [InlineKeyboardButton(
                f"{BOOKS['omf_pt']['emoji']} OMF (PT) — {PROMO_DISCOUNT_PCT}% OFF",
                callback_data="comprar_promo|omf_pt",
            )],
            [InlineKeyboardButton(
                f"{BOOKS['omf_en']['emoji']} OMF (EN) — {PROMO_DISCOUNT_PCT}% OFF",
                callback_data="comprar_promo|omf_en",
            )],
        ]
    )
    await update.message.reply_text(
        f"🔥 *PROMOÇÃO RELÂMPAGO — {PROMO_DISCOUNT_PCT}% de desconto\\!*\n\n"
        f"Por apenas *{mins} minutos*, todos os livros com desconto especial\\!\n\n"
        "⚡ Garanta agora antes que acabe — a oferta some automaticamente\\!\n\n"
        f"🔹 Anti\\-Líder: ~~R\\$ 32,00~~ → *R\\$ {32.0*(1-PROMO_DISCOUNT_PCT/100):.2f}*\n"
        f"🔹 OMF \\(PT\\): ~~R\\$ 32,00~~ → *R\\$ {32.0*(1-PROMO_DISCOUNT_PCT/100):.2f}*\n"
        f"🔹 OMF \\(EN\\): ~~R\\$ 84,00~~ → *R\\$ {84.0*(1-PROMO_DISCOUNT_PCT/100):.2f}*",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


async def cmd_amazon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a estratégia de vendas na Amazon com links para cada livro."""
    buttons = []
    for book_id, book in BOOKS.items():
        url = book.get("amazon_url", "")
        if url:
            buttons.append(
                [InlineKeyboardButton(
                    f"{book['emoji']} {book['title']} — Amazon",
                    url=url,
                )]
            )

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    suffix = (
        "\n\nClique nos botões abaixo para acessar as páginas na Amazon\\."
        if buttons
        else (
            "\n\n_Os links da Amazon ainda não foram configurados\\. "
            "Configure as variáveis de ambiente `AMAZON_URL_ANTILIDER`, "
            "`AMAZON_URL_OMF_PT` e `AMAZON_URL_OMF_EN` para ativá\\-los\\._"
        )
    )

    await update.message.reply_text(
        AMAZON_STRATEGY_TEXT + suffix,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )


async def callback_select_book(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usuário seleciona um livro."""
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
    count = purchase_counts.get(book_id, 0)
    price_display = f"R\\$ {book['price']:.2f}"
    if book_id == "omf_en":
        price_display = f"R\\$ {book['price']:.2f} \\($14\\.00 USD\\)"

    # Verifica se há promoção ativa
    promo_line = ""
    if PROMO_ACTIVE and _time.time() < PROMO_END_TIME:
        discounted = book["price"] * (1 - PROMO_DISCOUNT_PCT / 100)
        remaining = int(PROMO_END_TIME - _time.time())
        mins = remaining // 60
        secs = remaining % 60
        promo_line = (
            f"\n\n🔥 *PROMOÇÃO ATIVA\\!* De ~~{price_display}~~ por "
            f"*R\\$ {discounted:.2f}* \\— faltam *{mins:02d}:{secs:02d}*"
        )
        callback_buy = f"comprar_promo|{book_id}"
    else:
        callback_buy = f"comprar|{book_id}"

    pay_row = [InlineKeyboardButton(f"💳 Pagar {price_display}", callback_data=callback_buy)]
    amazon_url = book.get("amazon_url", "")
    rows = [pay_row]
    if amazon_url:
        rows.append([InlineKeyboardButton("🛒 Ver na Amazon", url=amazon_url)])

    # Prova social + escassez emocional
    social_proof = (
        f"👥 *{count} leitores* já adquiriram este livro\\!\n"
        "📈 _Avaliação média: ⭐⭐⭐⭐⭐_\n\n"
    )

    await query.message.reply_text(
        f"📖 Você selecionou: *{book['title']}*\n\n"
        f"{social_proof}"
        f"💰 Preço: {price_display}{promo_line}\n\n"
        "Clique abaixo para garantir o seu exemplar agora\\!",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _build_preference(book: dict, book_id: str, chat_id: int, unit_price: float) -> tuple[str, str]:
    """Cria uma preferência no Mercado Pago e retorna (external_ref, checkout_url)."""
    external_ref = f"{book_id}-{chat_id}-{uuid.uuid4().hex[:8]}"
    pending_payments[external_ref] = (chat_id, book_id)

    preference_data = {
        "items": [
            {
                "title": book["title"],
                "quantity": 1,
                "unit_price": round(unit_price, 2),
                "currency_id": book["currency"],
                "description": book["description"],
            }
        ],
        "external_reference": external_ref,
        "payment_methods": {"installments": 3},
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

    resp = mp_sdk.preference().create(preference_data)
    checkout_url = resp.get("response", {}).get("init_point", "")
    return external_ref, checkout_url


async def _send_payment_link(
    query,
    book: dict,
    book_id: str,
    unit_price: float,
    price_label: str,
) -> None:
    """Gera o link de pagamento e envia ao usuário."""
    chat_id = query.message.chat_id
    try:
        external_ref, checkout_url = _build_preference(book, book_id, chat_id, unit_price)
        if not checkout_url:
            await query.message.reply_text(
                "❌ Erro ao gerar o link de pagamento\\. Tente novamente mais tarde\\.",
                parse_mode="MarkdownV2",
            )
            return
        logger.info("Preferência criada — Ref: %s | Livro: %s | Chat: %s", external_ref, book_id, chat_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💳 Pagar {price_label}", url=checkout_url)],
            [InlineKeyboardButton("🔄 Já paguei — verificar", callback_data=f"verificar|{external_ref}")],
        ])
        await query.message.reply_text(
            PAYMENT_GENERATED_TEXT,
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Erro ao criar preferência de pagamento")
        await query.message.reply_text(
            "❌ Erro inesperado ao processar sua compra\\. Tente novamente\\.",
            parse_mode="MarkdownV2",
        )


async def callback_comprar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gera o link de pagamento ao preço normal."""
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
    price_label = f"R\\$ {book['price']:.2f}"
    await _send_payment_link(query, book, book_id, book["price"], price_label)


async def callback_comprar_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gera o link de pagamento com desconto promocional."""
    query = update.callback_query
    await query.answer()
    data_parts = query.data.split("|", 1)
    if len(data_parts) < 2:
        return
    book_id = data_parts[1]
    if book_id not in BOOKS:
        await query.message.reply_text("❌ Livro não encontrado.")
        return

    if not PROMO_ACTIVE or _time.time() >= PROMO_END_TIME:
        # Promoção expirou — cobra preço normal
        book = BOOKS[book_id]
        price_label = f"R\\$ {book['price']:.2f}"
        await query.message.reply_text(
            "⏰ A promoção expirou\\. Gerando link com preço normal\\.",
            parse_mode="MarkdownV2",
        )
        await _send_payment_link(query, book, book_id, book["price"], price_label)
        return

    book = BOOKS[book_id]
    discounted = book["price"] * (1 - PROMO_DISCOUNT_PCT / 100)
    price_label = f"R\\$ {discounted:.2f} \\(🔥 {PROMO_DISCOUNT_PCT}% OFF\\)"
    await _send_payment_link(query, book, book_id, discounted, price_label)


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
        # Busca pagamentos pela referência externa
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


def _upsell_message(book_id: str) -> str:
    """Retorna uma mensagem de upsell para os outros livros da coleção."""
    other_books = [
        (bid, b) for bid, b in BOOKS.items() if bid != book_id
    ]
    if not other_books:
        return ""
    lines = ["📚 *Complete sua coleção e aprofunde sua jornada:*\n"]
    for bid, b in other_books:
        price_str = f"R\\$ {b['price']:.2f}"
        lines.append(f"🔹 {b['emoji']} *{b['title']}* — {price_str}")
    lines.append("\n_Digite /start para adquirir outro título com desconto especial\\!_")
    return "\n".join(lines)


async def _deliver_book(bot, chat_id: int, book_id: str) -> None:
    """Envia o PDF ao comprador via file_id (preferencial) ou arquivo local."""
    book = BOOKS[book_id]
    payment_text = PAYMENT_APPROVED_TEXT_TEMPLATE.format(book_title=book["title"])
    await bot.send_message(chat_id=chat_id, text=payment_text, parse_mode="MarkdownV2")

    file_id = BOOK_FILE_IDS.get(book_id, "")
    if file_id:
        # Entrega rápida via file_id do Telegram (sem precisar do PDF no servidor)
        await bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=f"📖 {book['title']} — Seu exemplar digital",
        )
    else:
        # Fallback: lê o arquivo do disco
        pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), book["pdf_filename"])
        with open(pdf_path, "rb") as pdf_file:
            await bot.send_document(
                chat_id=chat_id,
                document=pdf_file,
                filename=f"{book['title']}.pdf",
                caption=f"📖 {book['title']} — Seu exemplar digital",
            )

    upsell = _upsell_message(book_id)
    if upsell:
        await bot.send_message(chat_id=chat_id, text=upsell, parse_mode="MarkdownV2")


async def send_book(chat_id: int, book_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia o PDF do livro para o comprador e incrementa o contador de vendas."""
    if book_id not in BOOKS:
        logger.error("Livro não encontrado: %s", book_id)
        return

    purchase_counts[book_id] = purchase_counts.get(book_id, 0) + 1

    try:
        await _deliver_book(context.bot, chat_id, book_id)
        logger.info("Livro %s enviado com sucesso para chat_id=%s", book_id, chat_id)
    except FileNotFoundError:
        logger.error("PDF não encontrado para %s", book_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Erro ao enviar o livro. Entre em contato com o suporte.",
        )
    except Exception:
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
        purchase_counts[book_id] = purchase_counts.get(book_id, 0) + 1
        await _deliver_book(telegram_app.bot, chat_id, book_id)
        logger.info("Livro %s enviado via webhook para chat_id=%s", book_id, chat_id)
    except FileNotFoundError:
        logger.error("PDF não encontrado para %s", book_id)
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
    elif data.startswith("comprar_promo|"):
        await callback_comprar_promo(update, context)
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

            # Responde imediatamente ao Mercado Pago
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

            # Processa a notificação em background
            action = data.get("action", "")
            topic = data.get("topic", "")
            data_id = data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else None

            # Também verifica query string (IPN usa ?topic=payment&id=xxx)
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
                # Busca a merchant_order para obter os pagamentos
                order_response = mp_sdk.merchant_order().get(resource_id)
                order = order_response.get("response", {})
                payments = order.get("payments", [])
                external_ref = order.get("external_reference", "")

                approved = any(p.get("status") == "approved" for p in payments)
            else:
                # Busca o pagamento diretamente
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
                # Envia o livro de forma assíncrona
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
    logger.info("  BOT MULTI-LIVROS — Iniciando...")
    logger.info("=" * 50)

    # Verifica se todos os PDFs existem
    for book_id, book in BOOKS.items():
        pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), book["pdf_filename"])
        if not Path(pdf_path).is_file():
            logger.error("ERRO: Arquivo PDF não encontrado em %s", pdf_path)
            logger.error("Coloque o arquivo '%s' na mesma pasta do bot.", book["pdf_filename"])
            return

    logger.info("✅ Todos os PDFs encontrados:")
    for book_id, book in BOOKS.items():
        logger.info("   • %s (%s) — R$ %.2f", book["title"], book["pdf_filename"], book["price"])

    # Inicia o servidor webhook em uma thread separada
    if WEBHOOK_BASE_URL:
        logger.info("Webhook configurado: %s/webhook", WEBHOOK_BASE_URL)
    else:
        logger.info(
            "WEBHOOK_BASE_URL não configurada. "
            "O bot funcionará com verificação manual (botão 'Já paguei')."
        )

    webhook_thread = Thread(target=start_webhook_server, daemon=True)
    webhook_thread.start()

    # Cria a aplicação do Telegram
    telegram_app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # Registra os handlers
    telegram_app.add_handler(CommandHandler("start", cmd_start))
    telegram_app.add_handler(CommandHandler("grupos", cmd_grupos))
    telegram_app.add_handler(CommandHandler("promo", cmd_promo))
    telegram_app.add_handler(CommandHandler("amazon", cmd_amazon))
    telegram_app.add_handler(CommandHandler("getfileid", cmd_getfileid))
    telegram_app.add_handler(CallbackQueryHandler(callback_router))

    # Inicia o polling
    logger.info("Bot rodando via polling. Pressione Ctrl+C para parar.")
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
