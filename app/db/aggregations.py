'''# app/db/aggregations.py
from pymongo.collection import Collection
from typing import Optional, Dict


def count_total(collection: Collection, entity: str, creator: Optional[str] = None) -> int:
    """
    Count total documents or distinct values based on entity type and optional creator.
    Works for: quotes, accounts, opportunities.
    """
    query_filter = {}
    if creator:
        creator_regex = {"$regex": creator.strip(), "$options": "i"}
        query_filter["$or"] = [
            {"created_by": creator_regex},
            {"user_id": creator_regex},
            {"quote_owner": creator_regex},
            {"peopleName": creator_regex},
        ]

    entity_lower = entity.lower()

    if entity_lower in ["quote", "quotes"]:
        return collection.count_documents(query_filter)
    elif entity_lower in ["account", "accounts"]:
        unique_accounts = collection.distinct("accounts", query_filter)
        return len([a for a in unique_accounts if a and str(a).strip()])
    elif entity_lower in ["opportunity", "opportunities"]:
        unique_opps = collection.distinct("opportunity_name", query_filter)
        return len([o for o in unique_opps if o and str(o).strip()])
    else:
        raise ValueError(f"The requested count is empty or '{entity}'")


def count_by_account(collection: Collection, account_name: str, entity: str) -> int:
    """
    Count entities related to a specific account.
    Works for: opportunities, quotes.
    """
    query_filter = {"accounts": {"$regex": f"^{account_name}$", "$options": "i"}}
    entity_lower = entity.lower()

    if entity_lower in ["opportunity", "opportunities"]:
        unique_opps = collection.distinct("opportunity_name", query_filter)
        return len([o for o in unique_opps if o and str(o).strip()])
    elif entity_lower in ["quote", "quotes"]:
        return collection.count_documents(query_filter)
    else:
        raise ValueError(f"Entity '{entity}' not supported for account-based count.")


def count_by_opportunity(collection: Collection, opportunity_name: str, entity: str) -> int:
    """
    Count entities related to a specific opportunity.
    Works for: quotes, accounts.
    """
    query_filter = {"opportunity_name": {"$regex": f"^{opportunity_name}$", "$options": "i"}}
    entity_lower = entity.lower()

    if entity_lower in ["quote", "quotes"]:
        return collection.count_documents(query_filter)
    elif entity_lower in ["account", "accounts"]:
        unique_accounts = collection.distinct("accounts", query_filter)
        return len([a for a in unique_accounts if a and str(a).strip()])
    else:
        raise ValueError(f"Entity '{entity}' not supported for opportunity-based count.")


def count_by_owner(collection: Collection, owner_name: str) -> Dict[str, int]:
    """
    Returns counts of quotes, accounts, opportunities created by a specific owner.
    """
    owner_regex = {"$regex": owner_name.strip(), "$options": "i"}
    query_filter = {"$or": [
        {"created_by": owner_regex},
        {"user_id": owner_regex},
        {"quote_owner": owner_regex},
        {"peopleName": owner_regex},
    ]}

    quotes_count = collection.count_documents(query_filter)
    accounts_count = len(collection.distinct("accounts", query_filter))
    opportunities_count = len(collection.distinct("opportunity_name", query_filter))

    return {
        "quotes": quotes_count,
        "accounts": accounts_count,
        "opportunities": opportunities_count
    }


def aggregate_field_sum(collection: Collection, group_by_field: str, sum_field: str) -> list:
    """
    Generic aggregation: sums a numeric field grouped by another field.
    Example: total sum of 'amount' grouped by 'status'.
    """
    pipeline = [
        {"$group": {"_id": f"${group_by_field}", f"total_{sum_field}": {"$sum": f"${sum_field}"}}}
    ]
    return list(collection.aggregate(pipeline))'''

# app/db/aggregations.py

# app/db/aggregations.py

from pymongo.collection import Collection
from typing import Optional, Dict


def count_total(collection: Collection, entity: str, creator: Optional[str] = None) -> int:
    """
    Count total documents or distinct values based on entity type and optional creator.
    Works for: quotes, accounts, opportunities.
    """
    query_filter = {}
    if creator:
        creator_regex = {"$regex": creator.strip(), "$options": "i"}
        query_filter["$or"] = [
            {"created_by": creator_regex},
            {"user_id": creator_regex},
            {"quote_owner": creator_regex},
            {"peopleName": creator_regex},
        ]

    entity_lower = entity.lower()

    if entity_lower in ["quote", "quotes"]:
        return collection.count_documents(query_filter)
    elif entity_lower in ["account", "accounts"]:
        unique_accounts = collection.distinct("accounts", query_filter)
        return len([a for a in unique_accounts if a and str(a).strip()])
    elif entity_lower in ["opportunity", "opportunities"]:
        unique_opps = collection.distinct("opportunity_name", query_filter)
        return len([o for o in unique_opps if o and str(o).strip()])
    else:
        raise ValueError(f"The requested count is empty or '{entity}'")


def count_by_account(collection: Collection, account_name: str, entity: str) -> int:
    """
    Count entities related to a specific account.
    Works for: opportunities, quotes.
    """
    query_filter = {"accounts": {"$regex": f"^{account_name.strip()}$", "$options": "i"}}
    entity_lower = entity.lower()

    if entity_lower in ["opportunity", "opportunities"]:
        unique_opps = collection.distinct("opportunity_name", query_filter)
        return len([o for o in unique_opps if o and str(o).strip()])
    elif entity_lower in ["quote", "quotes"]:
        return collection.count_documents(query_filter)
    else:
        raise ValueError(f"Entity '{entity}' not supported for account-based count.")


def count_by_opportunity(collection: Collection, opportunity_name: str, entity: str) -> int:
    """
    Count entities related to a specific opportunity.
    Works for: quotes, accounts.
    """
    query_filter = {"opportunity_name": {"$regex": f"^{opportunity_name.strip()}$", "$options": "i"}}
    entity_lower = entity.lower()

    if entity_lower in ["quote", "quotes"]:
        return collection.count_documents(query_filter)
    elif entity_lower in ["account", "accounts"]:
        unique_accounts = collection.distinct("accounts", query_filter)
        return len([a for a in unique_accounts if a and str(a).strip()])
    else:
        raise ValueError(f"Entity '{entity}' not supported for opportunity-based count.")


def count_by_owner(collection: Collection, owner_name: str) -> Dict[str, int]:
    """
    Returns counts of quotes, accounts, opportunities created by a specific owner.
    """
    owner_regex = {"$regex": owner_name.strip(), "$options": "i"}
    query_filter = {"$or": [
        {"created_by": owner_regex},
        {"user_id": owner_regex},
        {"quote_owner": owner_regex},
        {"peopleName": owner_regex},
    ]}

    quotes_count = collection.count_documents(query_filter)
    accounts_count = len([a for a in collection.distinct("accounts", query_filter) if a and str(a).strip()])
    opportunities_count = len([o for o in collection.distinct("opportunity_name", query_filter) if o and str(o).strip()])

    return {
        "quotes": quotes_count,
        "accounts": accounts_count,
        "opportunities": opportunities_count
    }


def aggregate_field_sum(collection: Collection, group_by_field: str, sum_field: str) -> list:
    """
    Generic aggregation: sums a numeric field grouped by another field.
    Example: total sum of 'amount' grouped by 'status'.
    """
    pipeline = [
        {"$group": {"_id": f"${group_by_field}", f"total_{sum_field}": {"$sum": f"${sum_field}"}}}
    ]
    return list(collection.aggregate(pipeline))


def list_accounts(collection: Collection, creator: Optional[str] = None) -> list:
    """
    Returns a list of distinct account names, optionally filtered by creator.
    """
    query_filter = {}
    if creator:
        creator_regex = {"$regex": creator.strip(), "$options": "i"}
        query_filter["$or"] = [
            {"created_by": creator_regex},
            {"user_id": creator_regex},
            {"quote_owner": creator_regex},
            {"peopleName": creator_regex},
        ]

    unique_accounts = collection.distinct("accounts", query_filter)
    return [a for a in unique_accounts if a and str(a).strip()]
