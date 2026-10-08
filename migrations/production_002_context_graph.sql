-- Reconstructible graph projection for the Omneum production network.
-- PostgreSQL network.* remains authoritative.

BEGIN;

CREATE EXTENSION IF NOT EXISTS age;

LOAD 'age';

SET search_path = ag_catalog, "$user", public;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM ag_catalog.ag_graph
        WHERE name = 'omneum_network'
    ) THEN
        PERFORM ag_catalog.create_graph('omneum_network');
    END IF;
END
$$;

DO $$
DECLARE
    label_name text;
    label_kind "char";
BEGIN
    FOR label_name, label_kind IN
        SELECT * FROM (
            VALUES
                ('Source', 'v'::"char"),
                ('Claim', 'v'::"char"),
                ('OBSERVED', 'e'::"char"),
                ('DEPENDENT', 'e'::"char")
        ) AS labels(name, kind)
    LOOP
        IF EXISTS (
            SELECT 1
            FROM ag_catalog.ag_label l
            JOIN ag_catalog.ag_graph g ON g.graphid = l.graph
            WHERE g.name = 'omneum_network'
              AND l.name = label_name
              AND l.kind <> label_kind
        ) THEN
            RAISE EXCEPTION
                'Unexpected kind for production graph label %',
                label_name;
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM ag_catalog.ag_label l
            JOIN ag_catalog.ag_graph g ON g.graphid = l.graph
            WHERE g.name = 'omneum_network'
              AND l.name = label_name
        ) THEN
            IF label_kind = 'v' THEN
                PERFORM ag_catalog.create_vlabel(
                    'omneum_network',
                    label_name::cstring
                );
            ELSE
                PERFORM ag_catalog.create_elabel(
                    'omneum_network',
                    label_name::cstring
                );
            END IF;
        END IF;
    END LOOP;
END
$$;

COMMIT;
