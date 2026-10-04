"""Pure monthly cash-flow projection. All arithmetic uses integer cents."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def cents(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError("Amount must be finite.")
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError) as error:
        raise ValueError("Enter a valid money amount.") from error


def calculate(objects, transfers, consumption, start=0, end=11):
    """Return monthly object ledgers; fixed transfers are all-or-nothing.

    Carry forward -> external funding -> consumption -> prioritized transfers
    -> closing balances. Global priority ties follow the stored transfer order.
    Transfers run once each: cycles never cause repeated execution.
    """
    if not 0 <= start <= end <= 11:
        raise ValueError("Projection must be within January through December.")
    balances = {o["id"]: o["starting_cents"] for o in objects}
    names = {o["id"]: o["name"] for o in objects}
    ordered = sorted(transfers, key=lambda t: t["priority"])
    # Python's sort is stable: equal priorities retain the saved transfer order.
    # That matters because a later transfer sees the funds left by earlier ones.
    for item in consumption:
        if item["payer_id"] not in balances:
            raise ValueError("Every consumption plan needs a valid paying object.")
        if item["amount_cents"] < 0 or not 0 <= item["month"] <= 11:
            raise ValueError("Invalid consumption amount or month.")
    for transfer in ordered:
        if transfer["source_id"] not in balances or transfer["destination_id"] not in balances:
            raise ValueError("A transfer references a missing money object.")
        if transfer["source_id"] == transfer["destination_id"]:
            raise ValueError("Transfer source and destination must differ.")
        if (transfer["amount_cents"] < 0 or transfer["priority"] < 1
                or not 0 <= transfer["start_month"] <= transfer["end_month"] <= 11):
            raise ValueError("Invalid transfer parameters.")
    results = []
    for month in range(start, end + 1):
        ledger = {
            key: dict(opening=value, income=0, consumed=0, incoming=0,
                      outgoing=0, closing=value, issues=[])
            for key, value in balances.items()
        }
        for obj in objects:
            income = obj["monthly_income_cents"]
            if income < 0:
                raise ValueError("External funding cannot be negative.")
            balances[obj["id"]] += income
            ledger[obj["id"]]["income"] = income
        for item in consumption:
            if item["month"] != month:
                continue
            payer = item["payer_id"]
            balances[payer] -= item["amount_cents"]
            ledger[payer]["consumed"] += item["amount_cents"]
            if balances[payer] < 0:
                ledger[payer]["issues"].append(
                    f'{item["title"]}: consumption exceeds available funds '
                    f'by ${-balances[payer] / 100:,.2f}.'
                )
        for transfer in ordered:
            if not transfer["start_month"] <= month <= transfer["end_month"]:
                continue
            source, destination = transfer["source_id"], transfer["destination_id"]
            available = max(0, balances[source])
            amount = available if transfer["use_rest"] else transfer["amount_cents"]
            if amount > available:
                issue = (f'{names[source]} → {names[destination]}: skipped; '
                         f'requested ${amount / 100:,.2f}, available ${available / 100:,.2f}, '
                         f'shortfall ${(amount - available) / 100:,.2f}.')
                ledger[source]["issues"].append(issue)
                ledger[destination]["issues"].append(issue)
                continue
            balances[source] -= amount
            balances[destination] += amount
            ledger[source]["outgoing"] += amount
            ledger[destination]["incoming"] += amount
        for key, value in balances.items():
            ledger[key]["closing"] = value
        results.append((month, ledger))
    return results
