from dataclasses import dataclass

import pandas as pd
from django.http import QueryDict


FILTER_SPEC_VERSION = 1
MAX_CATEGORICAL_OPTIONS = 50
MISSING_TEXT_VALUES = {
    "",
    "na",
    "n/a",
    "none",
    "null",
    "np",
    "missing",
    "not applicable",
    "not collected",
    "uncalculated",
}


FIELD_LABELS = {
    "sra_accession": "SRA accession",
    "sra_bioproject": "BioProject",
    "sra_biosample": "BioSample",
    "assay_type": "Assay type",
    "query_containment_ani": "ANI",
    "collection_date_sam": "Collection date",
    "containment": "Containment",
    "geo_loc_name_country_calc": "Country",
    "geo_loc_name": "Geographic location",
    "lat_lon": "Coordinates",
    "organism": "Organism",
    "releasedate": "Release date",
    "librarysource": "Library source",
    "sample_name": "Sample name",
    "sample_title": "Sample title",
    "experiment_title": "Experiment title",
    "study_title": "Study title",
    "description": "Description",
    "host": "Host",
    "isolation_source": "Isolation source",
}

CATEGORICAL_FIELDS = {
    "assay_type",
    "geo_loc_name_country_calc",
    "librarysource",
}
RANGE_FIELDS = {
    "containment",
    "query_containment_ani",
    "collection_date_sam",
    "releasedate",
}
FILTER_FIELD_ORDER = [
    "geo_loc_name_country_calc",
    "assay_type",
    "librarysource",
    "organism",
    "sample_name",
    "sample_title",
    "experiment_title",
    "study_title",
    "description",
    "sra_accession",
    "sra_bioproject",
    "sra_biosample",
    "host",
    "isolation_source",
    "containment",
    "query_containment_ani",
    "collection_date_sam",
    "releasedate",
]


@dataclass
class FilterControl:
    field: str
    label: str
    operator: str
    options: list[str]
    value: object
    min_value: str
    max_value: str
    include_missing: bool
    unavailable: bool = False


@dataclass
class FilterChip:
    field: str
    label: str
    description: str
    unavailable: bool = False


def display_label(field):
    return FIELD_LABELS.get(field, field.replace("_", " ").capitalize())


def is_missing_series(series):
    as_text = series.fillna("").astype(str).str.strip().str.lower()
    return series.isna() | as_text.isin(MISSING_TEXT_VALUES)


def has_active_filters(filter_spec):
    return bool(normalize_filter_spec(filter_spec).get("rules"))


def normalize_filter_spec(filter_spec):
    if not isinstance(filter_spec, dict):
        return {"version": FILTER_SPEC_VERSION, "rules": []}
    rules = []
    for raw_rule in filter_spec.get("rules", []):
        if not isinstance(raw_rule, dict):
            continue
        field = str(raw_rule.get("field", "")).strip()
        operator = str(raw_rule.get("operator", "")).strip()
        if not field or operator not in {"contains", "in", "range", "missing"}:
            continue
        include_missing = bool(raw_rule.get("include_missing", False))
        rule = {
            "field": field,
            "operator": operator,
            "include_missing": include_missing,
        }
        if operator == "contains":
            value = str(raw_rule.get("value", "")).strip()
            if not value:
                continue
            rule["value"] = value
        elif operator == "in":
            value = raw_rule.get("value", [])
            if not isinstance(value, list):
                value = [value]
            value = [str(item).strip() for item in value if str(item).strip()]
            if not value:
                continue
            rule["value"] = value
        elif operator == "range":
            min_value = str(raw_rule.get("min", "")).strip()
            max_value = str(raw_rule.get("max", "")).strip()
            if not min_value and not max_value:
                continue
            rule["min"] = min_value
            rule["max"] = max_value
        rules.append(rule)
    return {"version": FILTER_SPEC_VERSION, "rules": rules}


def apply_filter_spec(df, filter_spec):
    filtered = df.copy()
    for rule in normalize_filter_spec(filter_spec)["rules"]:
        field = rule["field"]
        include_missing = rule.get("include_missing", False)
        if field not in filtered.columns:
            if include_missing:
                continue
            return filtered.iloc[0:0]

        series = filtered[field]
        missing_mask = is_missing_series(series)
        operator = rule["operator"]
        if operator == "contains":
            value = str(rule["value"])
            match_mask = series.fillna("").astype(str).str.contains(
                value, case=False, regex=False
            )
        elif operator == "in":
            allowed = {str(item).strip().lower() for item in rule["value"]}
            match_mask = series.fillna("").astype(str).str.strip().str.lower().isin(
                allowed
            )
        elif operator == "range":
            match_mask = range_match_mask(
                series, rule.get("min", ""), rule.get("max", "")
            )
        elif operator == "missing":
            match_mask = missing_mask
        else:
            continue

        if include_missing and operator != "missing":
            match_mask = match_mask | missing_mask
        filtered = filtered[match_mask]
    return filtered


def range_match_mask(series, min_value, max_value):
    if looks_like_date_range(series, min_value, max_value):
        values = pd.to_datetime(series, errors="coerce")
        lower = pd.to_datetime(min_value, errors="coerce") if min_value else None
        upper = pd.to_datetime(max_value, errors="coerce") if max_value else None
    else:
        values = pd.to_numeric(series, errors="coerce")
        lower = pd.to_numeric(min_value, errors="coerce") if min_value else None
        upper = pd.to_numeric(max_value, errors="coerce") if max_value else None

    mask = pd.Series(True, index=series.index)
    if lower is not None and not pd.isna(lower):
        mask = mask & (values >= lower)
    if upper is not None and not pd.isna(upper):
        mask = mask & (values <= upper)
    return mask & values.notna()


def looks_like_date_range(series, min_value, max_value):
    name = str(getattr(series, "name", "")).lower()
    if "date" in name:
        return True
    values = [value for value in [min_value, max_value] if value]
    return any("-" in str(value) for value in values)


def build_filter_spec_from_post(post_data):
    if not isinstance(post_data, QueryDict):
        normalized_post_data = QueryDict("", mutable=True)
        for key, value in post_data.items():
            if isinstance(value, list):
                normalized_post_data.setlist(key, value)
            else:
                normalized_post_data[key] = value
        post_data = normalized_post_data

    rules = []
    fields = set()
    for key in post_data:
        if "__" in key:
            fields.add(key.split("__", 1)[1])

    for field in fields:
        include_missing = post_data.get(f"include_missing__{field}") == "on"
        selected_values = [
            value.strip()
            for value in post_data.getlist(f"in__{field}")
            if value.strip()
        ]
        if selected_values:
            rules.append(
                {
                    "field": field,
                    "operator": "in",
                    "value": selected_values,
                    "include_missing": include_missing,
                }
            )
            continue

        contains_value = post_data.get(f"contains__{field}", "").strip()
        if contains_value:
            rules.append(
                {
                    "field": field,
                    "operator": "contains",
                    "value": contains_value,
                    "include_missing": include_missing,
                }
            )
            continue

        min_value = post_data.get(f"min__{field}", "").strip()
        max_value = post_data.get(f"max__{field}", "").strip()
        if min_value or max_value:
            rules.append(
                {
                    "field": field,
                    "operator": "range",
                    "min": min_value,
                    "max": max_value,
                    "include_missing": include_missing,
                }
            )
            continue

        if post_data.get(f"missing__{field}") == "on":
            rules.append({"field": field, "operator": "missing"})

    rules.sort(
        key=lambda rule: (
            FILTER_FIELD_ORDER.index(rule["field"])
            if rule["field"] in FILTER_FIELD_ORDER
            else 999
        )
    )
    return normalize_filter_spec({"version": FILTER_SPEC_VERSION, "rules": rules})


def merge_filter_spec_from_post(filter_spec, post_data):
    selected_field = str(post_data.get("filter_field", "")).strip()
    if not selected_field:
        return normalize_filter_spec(filter_spec)

    current_spec = remove_filter_from_spec(filter_spec, selected_field)
    submitted_spec = build_filter_spec_from_post(post_data)
    submitted_rules = [
        rule for rule in submitted_spec["rules"] if rule["field"] == selected_field
    ]
    return normalize_filter_spec(
        {
            "version": FILTER_SPEC_VERSION,
            "rules": current_spec["rules"] + submitted_rules,
        }
    )


def remove_filter_from_spec(filter_spec, field):
    field = str(field).strip()
    spec = normalize_filter_spec(filter_spec)
    return {
        "version": FILTER_SPEC_VERSION,
        "rules": [rule for rule in spec["rules"] if rule["field"] != field],
    }


def build_addable_filter_fields(df, filter_spec):
    known_fields = [field for field in FILTER_FIELD_ORDER if field in df.columns]
    known_fields.extend(
        sorted(
            field
            for field in df.columns
            if field not in known_fields and field not in {"lat_lon"}
        )
    )
    selected_fields = {
        rule["field"] for rule in normalize_filter_spec(filter_spec)["rules"]
    }
    return [
        {
            "field": field,
            "label": display_label(field),
            "is_active": field in selected_fields,
        }
        for field in known_fields
        if field != "lat_lon"
    ]


def build_filter_control(df, filter_spec, selected_field):
    if not selected_field:
        return None
    selected_field = str(selected_field).strip()
    spec = normalize_filter_spec(filter_spec)
    rule = next(
        (rule for rule in spec["rules"] if rule["field"] == selected_field),
        {},
    )
    if selected_field not in df.columns:
        return FilterControl(
            field=selected_field,
            label=display_label(selected_field),
            operator=rule.get("operator", control_operator_for_field(selected_field)),
            options=[],
            value=rule.get("value", ""),
            min_value=rule.get("min", ""),
            max_value=rule.get("max", ""),
            include_missing=bool(rule.get("include_missing", False)),
            unavailable=True,
        )
    return FilterControl(
        field=selected_field,
        label=display_label(selected_field),
        operator=control_operator_for_field(selected_field),
        options=(
            categorical_options(df[selected_field])
            if selected_field in CATEGORICAL_FIELDS
            else []
        ),
        value=rule.get(
            "value", [] if selected_field in CATEGORICAL_FIELDS else ""
        ),
        min_value=rule.get("min", ""),
        max_value=rule.get("max", ""),
        include_missing=bool(rule.get("include_missing", False)),
    )


def control_operator_for_field(field):
    if field in CATEGORICAL_FIELDS:
        return "in"
    if field in RANGE_FIELDS:
        return "range"
    return "contains"


def categorical_options(series):
    values = []
    missing_mask = is_missing_series(series)
    for value in sorted(series[~missing_mask].dropna().astype(str).unique()):
        if value:
            values.append(value)
        if len(values) >= MAX_CATEGORICAL_OPTIONS:
            break
    return values


def active_filter_labels(filter_spec):
    labels = []
    for rule in normalize_filter_spec(filter_spec)["rules"]:
        label = display_label(rule["field"])
        if rule["operator"] == "contains":
            description = f"{label} contains {rule['value']}"
        elif rule["operator"] == "in":
            description = f"{label}: {', '.join(rule['value'])}"
        elif rule["operator"] == "range":
            min_value = rule.get("min") or "any"
            max_value = rule.get("max") or "any"
            description = f"{label}: {min_value} to {max_value}"
        elif rule["operator"] == "missing":
            description = f"{label} is missing"
        else:
            continue
        if rule.get("include_missing") and rule["operator"] != "missing":
            description = f"{description} or missing"
        labels.append(description)
    return labels


def active_filter_chips(filter_spec, available_fields=None):
    available_fields = set(available_fields or [])
    chips = []
    for rule in normalize_filter_spec(filter_spec)["rules"]:
        label = display_label(rule["field"])
        chips.append(
            FilterChip(
                field=rule["field"],
                label=label,
                description=active_filter_description(rule, label),
                unavailable=bool(
                    available_fields and rule["field"] not in available_fields
                ),
            )
        )
    return chips


def active_filter_description(rule, label):
    if rule["operator"] == "contains":
        description = f"{label} contains {rule['value']}"
    elif rule["operator"] == "in":
        description = f"{label}: {', '.join(rule['value'])}"
    elif rule["operator"] == "range":
        min_value = rule.get("min") or "any"
        max_value = rule.get("max") or "any"
        description = f"{label}: {min_value} to {max_value}"
    elif rule["operator"] == "missing":
        description = f"{label} is missing"
    else:
        description = label
    if rule.get("include_missing") and rule["operator"] != "missing":
        description = f"{description} or missing"
    return description
