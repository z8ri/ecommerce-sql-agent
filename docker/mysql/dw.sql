SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS dw DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
GRANT ALL PRIVILEGES ON dw.* TO 'didilili'@'%';

-- 问数 Agent 运行时使用的只读账号：只有 SELECT 权限，即使上层的 SQL 检查被绕过，
-- 数据库本身也不会执行任何写操作
CREATE USER IF NOT EXISTS 'dw_ro'@'%' IDENTIFIED BY 'dw_ro_pass';
GRANT SELECT ON dw.* TO 'dw_ro'@'%';

USE dw;

-- 演示数仓：多渠道电商（2024-01-01 ~ 2025-12-31）
-- 这里只定义表结构，数据由 `uv run python -m app.scripts.seed_dw` 确定性生成并导入
-- 星型模型：7 张维度表 + 4 张事实表
--   fact_order       订单粒度（一行一个订单）
--   fact_order_item  订单明细粒度（一行一个订单商品）
--   fact_refund      退款粒度（一行一笔退款）
--   fact_traffic     日 x 店铺 x 渠道的流量粒度


DROP TABLE IF EXISTS dim_date;
CREATE TABLE dim_date
(
    date_id      INT PRIMARY KEY COMMENT 'yyyymmdd',
    full_date    DATE,
    year         INT,
    quarter      VARCHAR(4),
    month        INT,
    day          INT,
    weekday      VARCHAR(8),
    is_weekend   TINYINT,
    holiday_name VARCHAR(20)
);

DROP TABLE IF EXISTS dim_region;
CREATE TABLE dim_region
(
    region_id   VARCHAR(10) PRIMARY KEY,
    province    VARCHAR(30),
    city        VARCHAR(30),
    region_name VARCHAR(10),
    city_tier   VARCHAR(10)
);

DROP TABLE IF EXISTS dim_customer;
CREATE TABLE dim_customer
(
    customer_id      VARCHAR(12) PRIMARY KEY,
    gender           VARCHAR(4),
    age_group        VARCHAR(12),
    member_level     VARCHAR(12),
    register_date_id INT,
    register_channel VARCHAR(20),
    region_id        VARCHAR(10)
);

DROP TABLE IF EXISTS dim_shop;
CREATE TABLE dim_shop
(
    shop_id       VARCHAR(10) PRIMARY KEY,
    shop_name     VARCHAR(40),
    shop_type     VARCHAR(10),
    main_category VARCHAR(20),
    region_id     VARCHAR(10)
);

DROP TABLE IF EXISTS dim_product;
CREATE TABLE dim_product
(
    product_id    VARCHAR(10) PRIMARY KEY,
    product_name  VARCHAR(60),
    category_l1   VARCHAR(20),
    category_l2   VARCHAR(20),
    brand         VARCHAR(20),
    shop_id       VARCHAR(10),
    list_price    DECIMAL(10, 2)
);

DROP TABLE IF EXISTS dim_channel;
CREATE TABLE dim_channel
(
    channel_id   VARCHAR(10) PRIMARY KEY,
    channel_name VARCHAR(20),
    channel_type VARCHAR(20)
);

DROP TABLE IF EXISTS dim_coupon;
CREATE TABLE dim_coupon
(
    coupon_id        VARCHAR(10) PRIMARY KEY,
    coupon_name      VARCHAR(30),
    coupon_type      VARCHAR(10),
    threshold_amount DECIMAL(10, 2),
    face_value       DECIMAL(10, 2)
);

DROP TABLE IF EXISTS fact_order;
CREATE TABLE fact_order
(
    order_id          VARCHAR(24) PRIMARY KEY,
    customer_id       VARCHAR(12),
    shop_id           VARCHAR(10),
    channel_id        VARCHAR(10),
    region_id         VARCHAR(10),
    date_id           INT,
    coupon_id         VARCHAR(10) NULL,
    order_status      VARCHAR(10),
    gross_amount      DECIMAL(12, 2),
    discount_amount   DECIMAL(12, 2),
    shipping_fee      DECIMAL(8, 2),
    pay_amount        DECIMAL(12, 2),
    item_count        INT,
    is_new_customer   TINYINT,
    carrier           VARCHAR(20) NULL,
    ship_date_id      INT NULL,
    delivery_days     INT NULL,
    review_score      INT NULL,
    INDEX idx_order_date (date_id),
    INDEX idx_order_customer (customer_id),
    INDEX idx_order_shop (shop_id)
);

DROP TABLE IF EXISTS fact_order_item;
CREATE TABLE fact_order_item
(
    item_id     VARCHAR(30) PRIMARY KEY,
    order_id    VARCHAR(24),
    product_id  VARCHAR(10),
    quantity    INT,
    unit_price  DECIMAL(10, 2),
    item_amount DECIMAL(12, 2),
    INDEX idx_item_order (order_id),
    INDEX idx_item_product (product_id)
);

DROP TABLE IF EXISTS fact_refund;
CREATE TABLE fact_refund
(
    refund_id     VARCHAR(24) PRIMARY KEY,
    order_id      VARCHAR(24),
    date_id       INT,
    refund_amount DECIMAL(12, 2),
    refund_reason VARCHAR(20),
    INDEX idx_refund_order (order_id),
    INDEX idx_refund_date (date_id)
);

DROP TABLE IF EXISTS fact_traffic;
CREATE TABLE fact_traffic
(
    date_id    INT,
    shop_id    VARCHAR(10),
    channel_id VARCHAR(10),
    visitors   INT,
    page_views INT,
    cart_users INT,
    PRIMARY KEY (date_id, shop_id, channel_id)
);
