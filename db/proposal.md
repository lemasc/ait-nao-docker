### **Project Title: A Systematic Performance Evaluation of Database Optimization Strategies for a Web Application Backend**

This project will follow the systematic approach to compare three system configurations:

1.  **Baseline:** A web application with a PostgreSQL database and no specific query optimizations.
2.  **Indexed DB:** The same application with appropriate indexes added to the database tables.
3.  **Cached System:** The same application with a Redis caching layer for frequent read operations.

---

### **The Systematic 10-Step Approach**

#### **Step 1: State Goals and Define the System**

- **Goals of the Study:**

  1.  To quantify the performance improvement (in terms of response time and throughput) of a read-heavy web application when using database indexing versus a baseline.
  2.  To quantify the performance improvement when introducing a Redis caching layer compared to the baseline and the indexed database.
  3.  To analyze the resource utilization (CPU, Memory) tradeoffs for each configuration under varying user loads.
  4.  To determine the conditions (e.g., workload type, user concurrency) under which each optimization provides the most benefit.

- **System Boundaries:**
  - **Inside the System:** The components under test include:
    - A web application server (e.g., built with Python/Flask or Node.js/Express).
    - A PostgreSQL database server.
    - A Redis cache server (for the caching configuration).
    - The network connection between these components within a controlled environment (e.g., Docker Compose).
  - **Outside the System:**
    - The load generation tool (e.g., JMeter, Locust).
    - The client machine running the tests.
    - The underlying physical hardware and operating system.
    - External network latency (assumed to be zero in a local testbed).

#### **Step 2: List Services and Outcomes**

- **Service:** The primary service being evaluated is **"User Profile Data Retrieval"**. This simulates a common application feature, like fetching a user's profile page.

- **Possible Outcomes for a Single Request:**
  1.  **Done Correctly:** The correct user profile data is returned to the client (HTTP 200 OK).
  2.  **Done Incorrectly:** Incorrect or stale data is returned. (We will assume our implementation is correct, but for a caching system, this is a real possibility to consider).
  3.  **Cannot Do (Failure):** The request fails due to a timeout, a server error (HTTP 5xx), or the database connection pool being exhausted.

#### **Step 3: Select Metrics**

Based on the goals and outcomes, we will measure the following:

- **Speed (Responsiveness):**
  - **Average Response Time (ms):** The mean time from sending a request to receiving a complete response. (A "Lower is Better" metric).
  - **95th Percentile Response Time (ms):** The response time value that 95% of requests fall under. This helps to ignore outliers but still capture the "worst-case" user experience better than the mean.
- **Rate (Productivity):**
  - **Throughput (requests/second):** The total number of successful requests completed per second. (A "Higher is Better" metric).
- **Resource Utilization:**
  - **CPU Utilization (%):** On the application server and the database server. (A "Nominal is Best" metric; too high indicates a bottleneck, too low indicates wasted resources).
  - **Memory Usage (MB):** On the Redis server.
- **Reliability/Availability:**
  - **Error Rate (%):** The percentage of failed requests (HTTP 5xx).
- **Cache-Specific Metric:**
  - **Cache Hit Ratio (%):** (For the Redis configuration) The percentage of read requests served directly from the cache.

#### **Step 4: List Parameters**

- **System Parameters:**

  - Database schema (presence/absence of indexes on the `username` column).
  - Presence/absence of a Redis cache.
  - Cache configuration (e.g., cache eviction policy, TTL).
  - Hardware allocation (CPU cores, RAM for each container).

- **Workload Parameters:**
  - Number of concurrent users.
  - Total number of users in the database (e.g., 1 million records).
  - Read/Write ratio of the workload.
  - "Think time" between user requests.
  - Distribution of requests (e.g., are some users requested far more often?).

#### **Step 5: Select Factors to Study**

From the parameter list, we will vary the following factors to study their effects. Other parameters will be kept constant (fixed).

- **Factor 1: System Configuration (Primary Factor)**

  - _Level 1:_ Baseline (No Index, No Cache)
  - _Level 2:_ Indexed DB (Index on `username`, No Cache)
  - _Level 3:_ Cached System (Index on `username`, Redis Cache)

- **Factor 2: Concurrent User Load**

  - _Level 1:_ Low (e.g., 20 concurrent users)
  - _Level 2:_ Medium (e.g., 100 concurrent users)
  - _Level 3:_ High (e.g., 500 concurrent users)

- **Factor 3: Workload Mix (Read/Write Ratio)**
  - _Level 1:_ Read-Heavy (95% reads, 5% writes) - _Simulates a social media or content site._
  - _Level 2:_ Balanced (50% reads, 50% writes) - _Simulates a more transactional application._

#### **Step 6: Select Evaluation Technique**

- **Technique:** **Measurement on a controlled testbed.** We will use real software (Python app, PostgreSQL, Redis) but run it in a controlled, emulated environment to ensure repeatability.
- **Tools:**
  - **Environment:** Docker and Docker Compose to define and run the multi-container application.
  - **Load Generation:** **Locust** (a Python-based tool) to create the synthetic workload and measure response times/throughput.
  - **Monitoring:** `docker stats` and `htop` for live resource monitoring; Prometheus for more advanced collection.

#### **Step 7: Select Workload**

The workload will be a synthetic script executed by Locust.

- A database will be pre-populated with 1,000,000 user records.
- The workload will simulate users performing two actions:
  1.  **Read Operation:** `GET /users/{username}` - Fetches a user's profile.
  2.  **Write Operation:** `PUT /users/{username}` - Updates a user's profile information.
- The `username`s to query will follow a **Zipfian distribution**, simulating that some users are "popular" and accessed frequently, which is ideal for testing caching effectiveness.
- The ratio of read-to-write operations will be controlled as defined in Factor 3.

#### **Step 8: Design Experiment**

We will use a **Full Factorial Experimental Design**. This means we will run an experiment for every possible combination of our factor levels.

- **Total Experiments:** 3 (System Configs) × 3 (User Loads) × 2 (Workload Mixes) = **18 unique experimental runs**.
- **Replication:** Each unique experiment will be repeated **3 times** to ensure statistical validity and allow for the calculation of confidence intervals.
- **Procedure for each run:**
  1.  Start the system configuration using Docker Compose.
  2.  Wait for the system to stabilize.
  3.  Run a 1-minute "warm-up" period with the specified load (data from this period is discarded).
  4.  Run the main measurement for a 5-minute duration, collecting all metrics.
  5.  Stop the load and tear down the environment.

#### **Step 9: Analyze and Interpret Data**

- For each of the 18 experimental settings, calculate the mean and standard deviation of the metrics across the 3 replications.
- **Data Analysis:**
  1.  Create summary tables showing the average response time, throughput, and error rate for each configuration and load level.
  2.  Use statistical methods (e.g., confidence intervals) to determine if the performance differences are statistically significant.
- **Interpretation:** Answer key questions such as:
  - "Under a read-heavy load, the indexed database reduced average response time by X% compared to the baseline, while the cached system reduced it by Y%."
  - "The CPU utilization on the database server decreased significantly with caching, as most requests were handled by Redis, but the application server's CPU usage increased slightly due to cache management logic."
  - "While indexing always helps, the benefit of caching diminishes significantly in the balanced 50/50 workload due to frequent cache invalidations, resulting in a low cache hit ratio of 35%."

#### **Step 10: Present Results**

The final report will communicate the findings clearly to both technical and managerial audiences.

- **Executive Summary:** A short, clear summary of the key findings (e.g., "For read-heavy applications, implementing a Redis cache yields a 10x improvement in throughput over the non-indexed baseline and is the recommended strategy for scaling.")
- **Visualizations:**
  - **Bar Charts:** To compare average response time and throughput across the three system configurations for each workload.
  - **Line Graphs:** To show how response time and throughput scale as the number of concurrent users increases for each configuration.
  - **Stacked Bar Charts:** To show CPU utilization of the app vs. database server.
- **Conclusions:** Restate the main findings and provide clear recommendations.
- **Assumptions and Limitations:** Clearly document the study's limitations (e.g., "This study did not model network latency," "The Zipfian workload distribution may not represent all real-world scenarios," "Cache warming strategies were not evaluated."). This directly addresses mistake #22 from your slides.
