with usine_a as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        -- num_serie dropped: always equals part_id (confirmed redundant)
        num_lot_prod,
        client,
        -- try_cast handles 999.9 sentinel and any malformed dates -> NULL
        try_cast(date_expedition as date)    as date_expedition,
        cast(quantite_lot       as integer)  as quantite_lot,
        certificat_conf,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm8_emballage') }}
),

usine_b as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        num_lot_prod,
        client,
        try_cast(date_expedition as date)    as date_expedition,
        cast(quantite_lot       as integer)  as quantite_lot,
        certificat_conf,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm8_emballage') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
