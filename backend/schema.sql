CREATE DATABASE IF NOT EXISTS agriculture_db;
USE agriculture_db;

CREATE TABLE IF NOT EXISTS users (
  user_id INT NOT NULL AUTO_INCREMENT,
  username VARCHAR(100) NOT NULL UNIQUE,
  email VARCHAR(255) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  otp VARCHAR(6) NULL,
  user_role VARCHAR(50) NOT NULL DEFAULT 'Farmer',
  mobile_number VARCHAR(20) NULL,
  aadhaar_number CHAR(12) NULL,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_mobile (mobile_number),
  UNIQUE KEY uq_users_aadhaar (aadhaar_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Existing DBs: db._bootstrap_schema adds mobile_number / aadhaar_number + indexes if missing.

CREATE TABLE IF NOT EXISTS farmer_profiles (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  mobile_number VARCHAR(20) NOT NULL,
  crop_type VARCHAR(100) NOT NULL,
  location VARCHAR(255) NOT NULL,
  land_size DECIMAL(10,2) NOT NULL,
  irrigation_type VARCHAR(100) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_farmer_profiles_user_id (user_id),
  CONSTRAINT fk_farmer_profiles_user_id
    FOREIGN KEY (user_id) REFERENCES users(user_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS farmers (
  farmer_id INT NOT NULL AUTO_INCREMENT,
  username VARCHAR(100) NOT NULL,
  mobile_number VARCHAR(20) NOT NULL,
  crop_type VARCHAR(100) NOT NULL,
  location VARCHAR(255) NOT NULL,
  land_size DECIMAL(10,2) NOT NULL,
  irrigation_type VARCHAR(100) NOT NULL,
  survey_number VARCHAR(100) NOT NULL,
  soil_report_file TEXT NOT NULL,
  PRIMARY KEY (username),
  UNIQUE KEY uq_farmers_farmer_id (farmer_id),
  CONSTRAINT fk_farmers_username
    FOREIGN KEY (username) REFERENCES users(username)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS experts (
  username VARCHAR(100) NOT NULL,
  mobile_number VARCHAR(20) NOT NULL,
  expertise_field VARCHAR(100) NOT NULL,
  experience_years INT NOT NULL,
  qualification TEXT NOT NULL,
  PRIMARY KEY (username),
  CONSTRAINT fk_experts_username
    FOREIGN KEY (username) REFERENCES users(username)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS soil_data (
  farmer_id INT NOT NULL,
  soil_ph DECIMAL(4,2) NOT NULL,
  nitrogen DECIMAL(10,2) NOT NULL,
  phosphorus DECIMAL(10,2) NOT NULL,
  potassium DECIMAL(10,2) NOT NULL,
  organic_carbon DECIMAL(10,2) NOT NULL,
  PRIMARY KEY (farmer_id),
  CONSTRAINT fk_soil_data_farmer_id
    FOREIGN KEY (farmer_id) REFERENCES farmers(farmer_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS market_prices (
  price_id INT NOT NULL AUTO_INCREMENT,
  crop_name VARCHAR(100) NOT NULL,
  market_location VARCHAR(255) NOT NULL,
  price DECIMAL(12,2) NOT NULL,
  price_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (price_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS government_schemes (
  scheme_id INT NOT NULL AUTO_INCREMENT,
  scheme_name VARCHAR(255) NOT NULL,
  description TEXT NOT NULL,
  eligibility TEXT NOT NULL,
  last_date DATE NOT NULL,
  PRIMARY KEY (scheme_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS activity_schedule (
  schedule_id INT NOT NULL AUTO_INCREMENT,
  farmer_id INT NOT NULL,
  activity_type VARCHAR(100) NOT NULL,
  activity_date DATE NOT NULL,
  reminder VARCHAR(20) NULL,
  PRIMARY KEY (schedule_id),
  CONSTRAINT fk_activity_schedule_farmer_id
    FOREIGN KEY (farmer_id) REFERENCES farmers(farmer_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE soil_data ADD location VARCHAR(100);

CREATE TABLE IF NOT EXISTS recommendations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    crop VARCHAR(50),
    seeds TEXT,
    fertilizer TEXT,
    location VARCHAR(100),
    mode VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
);

-- Expert queries support
ALTER TABLE expert_queries ADD COLUMN reply TEXT;

-- Existing deployments: `users.email` is added at runtime by db._bootstrap_schema if missing.
-- Manual one-off (ignore error if column already exists):
-- ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL;
