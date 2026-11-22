-- Run as the DCM role in the project's API schema after the table exists.
MERGE INTO DEMO_PRODUCTS AS target
USING DEMO_ITEMS AS seed ON target.ID = seed.ID
WHEN NOT MATCHED THEN INSERT (ID, ITEM, PRICE) VALUES (seed.ID, seed.ITEM, seed.PRICE);
