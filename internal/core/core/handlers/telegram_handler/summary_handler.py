"""Telegram handler for summary group management via inline keyboards + FSM."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.services.summary_service import SummaryService

logger = logging.getLogger(__name__)

summary_router = Router(name="summaries")


# ── Callback Data ─────────────────────────────────────────────────────

class SummaryCD(CallbackData, prefix="sg"):
    action: str  # menu, list, detail, add_chat, select_chat, rm_chat, del, interval, set_iv, back
    id: str = ""


class CreateCD(CallbackData, prefix="cs"):
    action: str  # toggle_chat, done, interval, cancel
    chat_id: str = ""


# ── FSM States ────────────────────────────────────────────────────────

class SummaryGroupForm(StatesGroup):
    waiting_for_name = State()
    selecting_chats = State()
    waiting_for_prompt = State()
    selecting_interval = State()


# ── Helpers ───────────────────────────────────────────────────────────

def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4cb Мои группы", callback_data=SummaryCD(action="list").pack())],
        [InlineKeyboardButton(text="\u2795 Создать группу", callback_data=SummaryCD(action="create").pack())],
    ])


def _back_btn(action: str = "menu", group_id: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="\u00ab Назад",
        callback_data=SummaryCD(action=action, id=group_id).pack(),
    )


def _interval_kb(prefix_cls, action: str, group_id: str = "") -> InlineKeyboardMarkup:
    intervals = [1, 3, 6, 12, 24]
    rows = []
    row = []
    for h in intervals:
        if prefix_cls == SummaryCD:
            cd = SummaryCD(action=action, id=f"{group_id}:{h}").pack()
        else:
            cd = CreateCD(action=action, chat_id=str(h)).pack()
        row.append(InlineKeyboardButton(text=f"{h}ч", callback_data=cd))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if prefix_cls == SummaryCD:
        rows.append([_back_btn("detail", group_id)])
    else:
        rows.append([InlineKeyboardButton(
            text="\u00ab Назад",
            callback_data=CreateCD(action="cancel").pack(),
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── /summaries command ────────────────────────────────────────────────

@summary_router.message(Command("summaries"))
async def cmd_summaries(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("\U0001f4ca Управление саммари-группами", reply_markup=_main_menu_kb())


# ── Main menu callback ───────────────────────────────────────────────

@summary_router.callback_query(SummaryCD.filter(F.action == "menu"))
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "\U0001f4ca Управление саммари-группами", reply_markup=_main_menu_kb()
    )


# ── List groups ──────────────────────────────────────────────────────

@summary_router.callback_query(SummaryCD.filter(F.action == "list"))
async def cb_list(
    callback: CallbackQuery,
    callback_data: SummaryCD,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    groups = await summary_service.get_user_groups(user_id)

    if not groups:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="\u2795 Создать группу",
                callback_data=SummaryCD(action="create").pack(),
            )],
            [_back_btn()],
        ])
        await callback.message.edit_text("У вас пока нет саммари-групп.", reply_markup=kb)
        return

    rows = []
    for g in groups:
        iv = g.get("interval_hours", "?")
        ch_count = len(g.get("channel_ids", []))
        rows.append([InlineKeyboardButton(
            text=f"\U0001f4c1 {g['name']} ({iv}ч, {ch_count} кан.)",
            callback_data=SummaryCD(action="detail", id=g["id"]).pack(),
        )])
    rows.append([_back_btn()])
    await callback.message.edit_text(
        "\U0001f4cb Ваши саммари-группы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


# ── Group detail ─────────────────────────────────────────────────────

@summary_router.callback_query(SummaryCD.filter(F.action == "detail"))
async def cb_detail(
    callback: CallbackQuery,
    callback_data: SummaryCD,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    group = await summary_service.get_group(callback_data.id)
    if not group:
        await callback.message.edit_text("Группа не найдена.", reply_markup=_main_menu_kb())
        return

    channels = group.get("channel_ids", [])
    ch_text = ", ".join(channels) if channels else "нет"
    prompt = group.get("prompt", "—")
    if len(prompt) > 200:
        prompt = prompt[:200] + "..."

    text = (
        f"\U0001f4c1 {group['name']}\n\n"
        f"\U0001f4dd Промпт: {prompt}\n\n"
        f"\U0001f4fa Каналы: {ch_text}\n\n"
        f"\u23f0 Интервал: {group.get('interval_hours', '?')}ч"
    )

    gid = group["id"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\u2795 Добавить чат",
                callback_data=SummaryCD(action="add_chat", id=gid).pack(),
            ),
            InlineKeyboardButton(
                text="\u23f0 Интервал",
                callback_data=SummaryCD(action="interval", id=gid).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="\U0001f5d1 Удалить",
                callback_data=SummaryCD(action="del", id=gid).pack(),
            ),
            _back_btn("list"),
        ],
    ])
    await callback.message.edit_text(text, reply_markup=kb)


# ── Delete group ─────────────────────────────────────────────────────

@summary_router.callback_query(SummaryCD.filter(F.action == "del"))
async def cb_delete(
    callback: CallbackQuery,
    callback_data: SummaryCD,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    deleted = await summary_service.delete_group(callback_data.id)
    text = "Группа удалена." if deleted else "Группа не найдена."
    await callback.message.edit_text(text, reply_markup=_main_menu_kb())


# ── Interval picker (existing group) ────────────────────────────────

@summary_router.callback_query(SummaryCD.filter(F.action == "interval"))
async def cb_interval(callback: CallbackQuery, callback_data: SummaryCD) -> None:
    await callback.answer()
    kb = _interval_kb(SummaryCD, "set_iv", callback_data.id)
    await callback.message.edit_text("\u23f0 Выберите интервал генерации:", reply_markup=kb)


@summary_router.callback_query(SummaryCD.filter(F.action == "set_iv"))
async def cb_set_interval(
    callback: CallbackQuery,
    callback_data: SummaryCD,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    # id contains "group_id:hours"
    parts = callback_data.id.rsplit(":", 1)
    if len(parts) != 2:
        return
    group_id, hours_str = parts
    try:
        hours = int(hours_str)
    except ValueError:
        return

    await summary_service.update_interval(group_id, hours)
    # Show detail again
    group = await summary_service.get_group(group_id)
    if group:
        callback_data_detail = SummaryCD(action="detail", id=group_id)
        await cb_detail(callback, callback_data_detail, summary_service)
    else:
        await callback.message.edit_text("Группа не найдена.", reply_markup=_main_menu_kb())


# ── Add/remove chat (existing group) ────────────────────────────────

@summary_router.callback_query(SummaryCD.filter(F.action == "add_chat"))
async def cb_add_chat(
    callback: CallbackQuery,
    callback_data: SummaryCD,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    group = await summary_service.get_group(callback_data.id)
    if not group:
        await callback.message.edit_text("Группа не найдена.", reply_markup=_main_menu_kb())
        return

    user_id = callback.from_user.id
    chats = await summary_service.get_available_chats(user_id)
    if not chats:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [_back_btn("detail", callback_data.id)],
        ])
        await callback.message.edit_text(
            "Не удалось получить список чатов.\n"
            "Убедитесь, что Telethon авторизован.",
            reply_markup=kb,
        )
        return

    current_ids = {str(c) for c in group.get("channel_ids", [])}
    rows = []
    for chat in chats:
        chat_id_str = str(chat.get("id", ""))
        title = chat.get("title", "?")
        in_group = chat_id_str in current_ids
        prefix = "\u2705" if in_group else "\u2b1c"
        rows.append([InlineKeyboardButton(
            text=f"{prefix} {title}",
            callback_data=SummaryCD(
                action="select_chat",
                id=f"{callback_data.id}:{chat_id_str}",
            ).pack(),
        )])
    rows.append([_back_btn("detail", callback_data.id)])
    await callback.message.edit_text(
        "\U0001f4fa Выберите чаты для группы:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@summary_router.callback_query(SummaryCD.filter(F.action == "select_chat"))
async def cb_select_chat(
    callback: CallbackQuery,
    callback_data: SummaryCD,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    # id contains "group_id:chat_id"
    parts = callback_data.id.rsplit(":", 1)
    if len(parts) != 2:
        return
    group_id, chat_id = parts

    group = await summary_service.get_group(group_id)
    if not group:
        return

    current_ids = [str(c) for c in group.get("channel_ids", [])]
    if chat_id in current_ids:
        await summary_service.remove_channel(group_id, chat_id)
    else:
        await summary_service.add_channel(group_id, chat_id)

    # Refresh the chat list
    fake_cd = SummaryCD(action="add_chat", id=group_id)
    await cb_add_chat(callback, fake_cd, summary_service)


# ── Create group (FSM) ───────────────────────────────────────────────

@summary_router.callback_query(SummaryCD.filter(F.action == "create"))
async def cb_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SummaryGroupForm.waiting_for_name)
    await state.update_data(selected_chats=[])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="\u2716 Отмена",
            callback_data=CreateCD(action="cancel").pack(),
        )],
    ])
    await callback.message.edit_text(
        "\u2795 Создание саммари-группы\n\nВведите название группы:",
        reply_markup=kb,
    )


@summary_router.message(SummaryGroupForm.waiting_for_name, F.text)
async def fsm_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(SummaryGroupForm.selecting_chats)
    await _show_chat_selection(message, state)


async def _show_chat_selection(
    target: Message,
    state: FSMContext,
    summary_service: SummaryService | None = None,
    edit: bool = False,
) -> None:
    data = await state.get_data()
    selected = set(data.get("selected_chats", []))
    chats = data.get("available_chats")

    if chats is None and summary_service:
        user_id = target.from_user.id if hasattr(target, "from_user") and target.from_user else target.chat.id
        chats = await summary_service.get_available_chats(user_id)
        await state.update_data(available_chats=chats)
    elif chats is None:
        chats = []

    rows = []
    for chat in chats:
        chat_id_str = str(chat.get("id", ""))
        title = chat.get("title", "?")
        prefix = "\u2705" if chat_id_str in selected else "\u2b1c"
        rows.append([InlineKeyboardButton(
            text=f"{prefix} {title}",
            callback_data=CreateCD(action="toggle_chat", chat_id=chat_id_str).pack(),
        )])
    rows.append([
        InlineKeyboardButton(
            text="\u2705 Готово",
            callback_data=CreateCD(action="done").pack(),
        ),
        InlineKeyboardButton(
            text="\u2716 Отмена",
            callback_data=CreateCD(action="cancel").pack(),
        ),
    ])

    text = "\U0001f4fa Выберите каналы/группы для мониторинга:"
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit and hasattr(target, "edit_text"):
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@summary_router.callback_query(SummaryGroupForm.selecting_chats, CreateCD.filter(F.action == "toggle_chat"))
async def fsm_toggle_chat(
    callback: CallbackQuery,
    callback_data: CreateCD,
    state: FSMContext,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    data = await state.get_data()
    selected = set(data.get("selected_chats", []))

    chat_id = callback_data.chat_id
    if chat_id in selected:
        selected.discard(chat_id)
    else:
        selected.add(chat_id)

    await state.update_data(selected_chats=list(selected))
    await _show_chat_selection(callback.message, state, summary_service, edit=True)


@summary_router.callback_query(SummaryGroupForm.selecting_chats, CreateCD.filter(F.action == "done"))
async def fsm_chats_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    selected = data.get("selected_chats", [])
    if not selected:
        await callback.answer("Выберите хотя бы один чат", show_alert=True)
        return

    await state.set_state(SummaryGroupForm.waiting_for_prompt)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="\u2716 Отмена",
            callback_data=CreateCD(action="cancel").pack(),
        )],
    ])
    await callback.message.edit_text(
        f"Выбрано каналов: {len(selected)}\n\n"
        "\U0001f4dd Введите промпт для генерации саммари:",
        reply_markup=kb,
    )


@summary_router.message(SummaryGroupForm.waiting_for_prompt, F.text)
async def fsm_prompt(message: Message, state: FSMContext) -> None:
    await state.update_data(prompt=message.text)
    await state.set_state(SummaryGroupForm.selecting_interval)
    kb = _interval_kb(CreateCD, "interval")
    await message.answer("\u23f0 Выберите интервал генерации саммари:", reply_markup=kb)


@summary_router.callback_query(SummaryGroupForm.selecting_interval, CreateCD.filter(F.action == "interval"))
async def fsm_interval(
    callback: CallbackQuery,
    callback_data: CreateCD,
    state: FSMContext,
    summary_service: SummaryService,
) -> None:
    await callback.answer()
    try:
        interval_hours = int(callback_data.chat_id)
    except ValueError:
        return

    data = await state.get_data()
    user_id = callback.from_user.id

    group_id = await summary_service.create_group(
        user_id=user_id,
        name=data["name"],
        prompt=data["prompt"],
        channel_ids=data["selected_chats"],
        interval_hours=interval_hours,
    )

    await state.clear()

    # Show detail of created group
    group = await summary_service.get_group(group_id)
    if group:
        channels = group.get("channel_ids", [])
        ch_text = ", ".join(str(c) for c in channels) if channels else "нет"
        prompt = group.get("prompt", "—")
        if len(prompt) > 200:
            prompt = prompt[:200] + "..."

        text = (
            f"\u2705 Группа создана!\n\n"
            f"\U0001f4c1 {group['name']}\n\n"
            f"\U0001f4dd Промпт: {prompt}\n\n"
            f"\U0001f4fa Каналы: {ch_text}\n\n"
            f"\u23f0 Интервал: {interval_hours}ч"
        )
        gid = group["id"]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="\u2795 Добавить чат",
                    callback_data=SummaryCD(action="add_chat", id=gid).pack(),
                ),
                InlineKeyboardButton(
                    text="\u23f0 Интервал",
                    callback_data=SummaryCD(action="interval", id=gid).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="\U0001f5d1 Удалить",
                    callback_data=SummaryCD(action="del", id=gid).pack(),
                ),
                _back_btn("list"),
            ],
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    else:
        await callback.message.edit_text(
            "\u2705 Группа создана!", reply_markup=_main_menu_kb()
        )


# ── Cancel FSM ───────────────────────────────────────────────────────

@summary_router.callback_query(CreateCD.filter(F.action == "cancel"))
async def fsm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "\U0001f4ca Управление саммари-группами", reply_markup=_main_menu_kb()
    )
