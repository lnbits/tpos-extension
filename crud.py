from typing import Optional, Union

from lnbits.db import Database
from lnbits.helpers import insert_query, update_query, urlsafe_short_hash
from loguru import logger

from .models import CreateTposData, LnurlCharge, Tpos, TposClean

db = Database("ext_tpos")


async def get_current_timestamp():
    # Get current DB timestamp
    timestamp_query = f"SELECT {db.timestamp_now}"
    if db.type in {"POSTGRES", "COCKROACH"}:
        timestamp_query = f"SELECT EXTRACT(EPOCH FROM {db.timestamp_now})"
    current_timestamp = (await db.fetchone(timestamp_query))[0]
    return int(current_timestamp)


async def create_tpos(data: CreateTposData) -> Tpos:
    tpos_id = urlsafe_short_hash()
    tpos = Tpos(id=tpos_id, **data.dict())
    await db.execute(
        insert_query("tpos.pos", tpos),
        tpos.dict(),
    )
    return tpos


async def get_tpos(tpos_id: str) -> Optional[Tpos]:
    row = await db.fetchone("SELECT * FROM tpos.pos WHERE id = :id", {"id": tpos_id})
    print(row)
    return Tpos(**row) if row else None


async def start_lnurlcharge(tpos_id: str):
    tpos = await get_tpos(tpos_id)
    assert tpos, f"TPoS with {tpos_id} not found!"

    now = await get_current_timestamp()
    withdraw_time_seconds = (
        tpos.withdraw_between * 60
        if tpos.withdraw_time_option != "secs"
        else tpos.withdraw_between
    )
    assert (
        now - tpos.withdraw_time > withdraw_time_seconds
    ), f"""
    Last withdraw was made too recently, please try again in
    {int(withdraw_time_seconds - (now - tpos.withdraw_time))} secs
    """

    token = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO tpos.withdraws (id, tpos_id)
        VALUES (:id, :tpos_id)
        """,
        {"id": token, "tpos_id": tpos_id},
    )
    lnurlcharge = await get_lnurlcharge(token)
    return lnurlcharge


async def get_lnurlcharge(lnurlcharge_id: str) -> Optional[LnurlCharge]:
    row = await db.fetchone(
        "SELECT * FROM tpos.withdraws WHERE id = :id", {"id": lnurlcharge_id}
    )
    return LnurlCharge(**row) if row else None


async def update_lnurlcharge(data: LnurlCharge) -> LnurlCharge:
    await db.execute(
        update_query("tpos.withdraws", data),
        data.dict(),
    )

    lnurlcharge = await get_lnurlcharge(data.id)
    assert lnurlcharge, "Withdraw couldn't be retrieved"

    return lnurlcharge


async def get_clean_tpos(tpos_id: str) -> Optional[TposClean]:
    row = await db.fetchone("SELECT * FROM tpos.pos WHERE id = :id", {"id": tpos_id})
    return TposClean(**row) if row else None


async def update_tpos_withdraw(data: Tpos, tpos_id: str) -> Tpos:
    # Calculate the time between withdrawals in seconds
    now = await get_current_timestamp()
    time_elapsed = now - data.withdraw_time
    withdraw_time_seconds = (
        data.withdraw_between * 60
        if data.withdraw_time_option != "secs"
        else data.withdraw_between
    )

    logger.debug(f"Time between: {time_elapsed} seconds")

    # Check if the time between withdrawals is less than withdrawbtwn
    assert (
        time_elapsed > withdraw_time_seconds
    ), f"""
    Last withdraw was made too recently, please try again in
    {int(withdraw_time_seconds - (time_elapsed))} secs"
    """

    # Update the withdraw time in the database
    await db.execute(
        "UPDATE tpos.pos SET withdrawtime = :time WHERE id = :id",
        {"time": now, "id": tpos_id},
    )

    tpos = await get_tpos(tpos_id)
    assert tpos, "Newly updated tpos couldn't be retrieved"
    return tpos


async def update_tpos(tpos: Tpos) -> Tpos:
    await db.execute(
        update_query("tpos.pos", tpos),
        tpos.dict(),
    )
    return tpos


async def get_tposs(wallet_ids: Union[str, list[str]]) -> list[Tpos]:
    if isinstance(wallet_ids, str):
        wallet_ids = [wallet_ids]
    q = ",".join([f"'{wallet_id}'" for wallet_id in wallet_ids])
    rows = await db.fetchall(f"SELECT * FROM tpos.pos WHERE wallet IN ({q})")
    return [Tpos(**row) for row in rows]


async def delete_tpos(tpos_id: str) -> None:
    await db.execute("DELETE FROM tpos.pos WHERE id = :id", {"id": tpos_id})
