"""Bridge the editable Flet models to storage and the pure calculation engine."""

from money_object import MoneyObject, FUNDING_FROM_OUTSIDE
from periodic_plan import PeriodicPlanEdge
from projection import calculate, cents


def snapshot(timeline):
    """Convert editable UI models into plain data for SQLite and calculation.

    Amounts become integer cents here. Generated balance cards are excluded;
    saving them would mix calculated results with the inputs that produced them.
    """
    # IDs survive renames; the name lookup supports older plans without IDs.
    ids = {obj.name: obj.object_id for obj in timeline.money_objects}
    return {
        "objects": [dict(id=obj.object_id, name=obj.name, category=obj.category,
                         starting_cents=cents(obj.current_amount),
                         monthly_income_cents=(cents(obj.monthly_income)
                                               if obj.funding_type == FUNDING_FROM_OUTSIDE else 0),
                         funding_type=obj.funding_type, external_source=obj.external_source)
                    for obj in timeline.money_objects],
        "transfers": [dict(id=plan.edge_id, title=plan.title,
                           source_id=plan.source_object_id or ids[plan.source],
                           destination_id=plan.destination_object_id or ids[plan.destination],
                           amount_cents=cents(plan.amount), use_rest=int(plan.use_rest),
                           priority=plan.priority, start_month=plan.start_month,
                           end_month=plan.end_month) for plan in timeline.periodic_plans],
        "consumption": [dict(id=box.box_id, payer_id=box.payer_id, title=box.title,
                             amount_cents=cents(box.amount), month=month.index)
                        for month in timeline.months for box in month.boxes
                        if not box.lane],
        "settings": {"source_order": list(timeline.source_object_order),
                     "destination_order": list(timeline.destination_object_order),
                     "projection_start": 0, "projection_end": 11},
    }


def restore(timeline, state):
    """Recreate objects first, then transfers and spending that reference them."""
    timeline.set_money_objects([
        MoneyObject(obj["id"], obj["name"], category=obj["category"],
                    current_amount=obj["starting_cents"] / 100,
                    funding_type=obj["funding_type"], external_source=obj["external_source"],
                    monthly_income=obj["monthly_income_cents"] / 100)
        for obj in state["objects"]
    ])
    timeline.source_object_order = state["settings"].get("source_order", [])
    timeline.destination_object_order = state["settings"].get("destination_order", [])
    timeline.replace_periodic_edge_plans([
        PeriodicPlanEdge("source:" + plan["source_id"], "destination:" + plan["destination_id"],
                         amount=plan["amount_cents"] / 100, use_rest=bool(plan["use_rest"]),
                         priority=plan["priority"], start_month=plan["start_month"],
                         end_month=plan["end_month"], edge_id=plan["id"])
        for plan in state["transfers"]
    ])
    titles = {plan["id"]: plan["title"] for plan in state["transfers"]}
    for plan in timeline.periodic_plans:
        plan.title = titles[plan.edge_id]
    for item in state["consumption"]:
        timeline.add_item(item["title"], month_index=item["month"],
                          amount=item["amount_cents"] / 100, payer_id=item["payer_id"],
                          consumption_id=item["id"])
    timeline._refresh_periodic_plans_view()


def refresh(timeline):
    """Save changed inputs, calculate every month, then rebuild balance cards."""
    state = snapshot(timeline)
    # Resize and other display-only updates need no database write or calculation.
    if state == timeline._last_state:
        return
    results = calculate(state["objects"], state["transfers"], state["consumption"])
    # Persist validated inputs before replacing the derived display.
    timeline.store.save(state)
    timeline.periodic_edges = [
        PeriodicPlanEdge("source:" + plan["source_id"], "destination:" + plan["destination_id"],
                         amount=plan["amount_cents"] / 100, use_rest=bool(plan["use_rest"]),
                         priority=plan["priority"], start_month=plan["start_month"],
                         end_month=plan["end_month"], edge_id=plan["id"])
        for plan in state["transfers"]
    ]
    for box in list(timeline._boxes.values()):
        # A lane marks a generated Sources/Savings card. Keep the user's spending
        # cards, but replace balances so they cannot display stale calculations.
        if box.lane:
            timeline._remove_box(box.box_id)
    for month_index, ledger in results:
        month = timeline.months[month_index]
        # Hidden months still participate in carry-forward calculations, but
        # only months with consumption need cards on the timeline.
        if not any(not box.lane for box in month.boxes):
            continue
        for obj in timeline.money_objects:
            values = ledger[obj.object_id]
            details = "\n".join([
                f'{obj.name} — {month.name}',
                f'Opening: ${values["opening"] / 100:,.2f}',
                f'External income: ${values["income"] / 100:,.2f}',
                f'Consumption: ${values["consumed"] / 100:,.2f}',
                f'Transfers in: ${values["incoming"] / 100:,.2f}',
                f'Transfers out: ${values["outgoing"] / 100:,.2f}',
                f'Closing: ${values["closing"] / 100:,.2f}',
                *values["issues"],
            ])
            for lane, amount in (("source", values["opening"] + values["income"]),
                                 ("destination", values["closing"])):
                box_id = f"projection:{month_index}:{lane}:{obj.object_id}"
                box = month.add_box(box_id, obj.name, lane=lane, amount=amount / 100)
                box.payer_id = obj.object_id
                box.warning = bool(values["issues"]) and lane == "destination"
                box.explanation = details
                box.on_edit = timeline.show_balance
                timeline._boxes[box_id] = box
                timeline.connector.add_object(box_id, box.as_connectable_object())
    timeline.projection = results
    names = {obj.object_id: obj.name for obj in timeline.money_objects}
    for month in timeline.months:
        for box in month.boxes:
            if not box.lane:
                box.source = names[box.payer_id]
                box.refresh_text()
                timeline.connector.connections.append(
                    (f"projection:{month.index}:source:{box.payer_id}", box.box_id)
                )
    timeline._last_state = state
    timeline._layout_visible_months()
