DEFINE SCHEMA {{ database_name }}.API
  COMMENT = 'Read-only FastAPI service and demonstration data';

DEFINE VIEW {{ database_name }}.API.DEMO_ITEMS AS
  SELECT column1::NUMBER(38,0) AS ID, column2::VARCHAR(30) AS ITEM,
         column3::NUMBER(12,2) AS PRICE
  FROM VALUES (1, 'Notebook', 4.95), (2, 'Pencil', 0.80), (3, 'Folder', 2.25),
              (4, 'Ruler', 1.50), (5, 'Eraser', 0.65);

DEFINE TABLE {{ database_name }}.API.DEMO_PRODUCTS (
  ID NUMBER(38,0) NOT NULL,
  ITEM VARCHAR(30) NOT NULL,
  PRICE NUMBER(12,2) NOT NULL,
  PRIMARY KEY (ID)
);

GRANT USAGE ON SCHEMA {{ database_name }}.API TO ROLE {{ reader_role }};
GRANT SELECT ON TABLE {{ database_name }}.API.DEMO_PRODUCTS TO ROLE {{ reader_role }};
GRANT USAGE ON SCHEMA {{ database_name }}.API TO ROLE {{ app_owner }};
