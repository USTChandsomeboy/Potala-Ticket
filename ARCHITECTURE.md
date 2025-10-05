# Potala-Ticket Agent Architecture Analysis

## Overview
This document analyzes the main parts and architecture of the Potala Palace ticket monitoring agent. The agent is a Python-based monitoring system that tracks ticket availability for the Potala Palace through a WeChat Mini-Program API.

## Main Components

### 1. Configuration Layer (Lines 26-49)
**Location**: `ticket.py` lines 26-49

The configuration section contains all the customizable parameters for the monitoring agent:

#### Core Settings
- **`BASE_URL`** (line 27): API endpoint for ticket queries (requires user to obtain through packet capture)
- **`HTTP_TIMEOUT`** (line 28): HTTP request timeout (10 seconds)
- **`MAX_RETRIES`** (line 29): Maximum retry attempts for failed requests (3 times)

#### Monitoring Parameters
- **`COMMODITY_IDS`** (line 32): List of route IDs to monitor (default: [1] for Potala Palace tickets)
- **`TARGET_DATES`** (line 33): Target dates to monitor (e.g., ["2025-10-01"])
- **`CHECK_INTERVAL_SEC`** (line 36): Polling interval when within booking window (60 seconds)
- **`JITTER_SEC`** (line 37): Random jitter to add to polling interval (10 seconds)
- **`EARLY_CHECK_INTERVAL_SEC`** (line 40): Low-frequency polling before booking window opens (12 hours)

#### Authentication & Notification
- **`SERVERCHAN_SENDKEY`** (line 43): Server酱 (ServerChan) API key for WeChat push notifications
- **`POTALA_TOKEN`** (line 46): Mini-Program authentication token
- **`LOG_FILE`** (line 49): Log file name for persistent logging

### 2. Initialization & Setup (Lines 51-85)

#### Logging Configuration (`setup_logging()`)
**Location**: Lines 51-71

Configures dual-output logging system:
- **File Handler**: Writes UTF-8 encoded logs to `potala_monitor.log`
- **Stream Handler**: Outputs logs to console
- **Format**: `%(asctime)s - %(levelname)s - %(message)s`

#### Session Management (`make_session()`)
**Location**: Lines 74-85

Creates a robust HTTP session with:
- **Automatic Retry**: Uses urllib3's Retry mechanism
- **Retry Strategy**: 
  - Total retries: 3
  - Backoff factor: 0.8 seconds
  - Status codes to retry: [429, 500, 502, 503, 504]
  - Allowed methods: GET, POST
- **Adapters**: Mounts HTTPAdapter for both HTTP and HTTPS protocols

### 3. API Communication Layer (Lines 87-103)

#### Headers Generation (`get_headers()`)
**Location**: Lines 87-103

Dynamically generates HTTP headers for each API request:
- **Token Refresh**: Reads `POTALA_TOKEN` from environment on each call
- **Required Fields**: Host, site-id, token, version, Referer (all obtained via packet capture)
- **Platform Identification**: Identifies as WeChat Mini-Program (`wxMiniProgram`)

### 4. Notification System (Lines 105-115)

#### ServerChan Integration (`notify_serverchan()`)
**Location**: Lines 105-115

Push notification system using Server酱 (ServerChan):
- **Function**: Sends WeChat notifications on ticket availability changes
- **API**: `https://sctapi.ftqq.com/{SENDKEY}.send`
- **Error Handling**: Logs warnings without interrupting the monitoring loop
- **Parameters**: 
  - `title`: Notification title
  - `content`: Notification body (supports Markdown)

### 5. Data Fetching & Parsing (Lines 118-157)

#### Status Enumeration (`FetchStatus`)
**Location**: Lines 118-121

Defines three states for API responses:
- **`OK`**: Successfully retrieved ticket data
- **`NOT_OPEN`**: Booking window not yet open
- **`ERROR`**: Request failed or token invalid

#### Slot Fetching (`fetch_slots()`)
**Location**: Lines 123-157

Core function for retrieving ticket availability:
- **Input**: 
  - `sess`: Requests session
  - `commodity_id`: Route ID
  - `date_str`: Target date (YYYY-MM-DD format)
- **Output**: Tuple of (status, slots, msg)
- **Logic**:
  1. Sends POST request with JSON payload
  2. Handles network exceptions
  3. Parses JSON response
  4. Distinguishes between "not open" and "error" states
  5. Detects token expiration ("请先登录")

### 6. Data Processing Utilities (Lines 159-179)

#### Ticket Formatting (`format_available_lines()`)
**Location**: Lines 159-170

Formats available time slots into readable strings:
- **Filters**: Only includes slots with `nums > 0` (tickets available)
- **Format**: `"{time_interval_str}：{nums} 张"` (e.g., "11:00-11:20：14 张")

#### Line Merging (`join_lines()`)
**Location**: Lines 172-174

Combines formatted lines into a single string for change detection:
- **Separator**: " | "
- **Purpose**: Enables comparison between current and previous states

#### Open Date Calculator (`compute_open_date()`)
**Location**: Lines 176-179

Calculates when booking opens based on the "15 days in advance" rule:
- **Rule**: Tickets for date X become available on X - 15 days
- **Output**: Python `date` object representing the opening date

### 7. Main Execution Loop (Lines 181-288)

#### Main Function (`main()`)
**Location**: Lines 181-285

The central orchestrator of the monitoring agent:

##### Initialization Phase (Lines 182-196)
1. Configures logging system
2. Creates HTTP session
3. Logs startup message
4. Initializes in-memory state cache (`last_pushed`)

##### State Cache Structure
```python
last_pushed: Dict[Tuple[int, str], Dict[str, str]]
# Key: (commodity_id, date_str)
# Value: {"status": "NOT_OPEN"|"NO_STOCK"|"HAS_STOCK", "payload": "..."}
```

##### Monitoring Loop (Lines 198-285)

The agent runs an infinite loop with the following phases:

**Phase 1: Pre-Booking Window (Lines 206-215)**
- Detects if current date < open date
- Logs days remaining until booking opens
- Updates state to "NOT_OPEN"
- Continues to next iteration (low-frequency polling)

**Phase 2: API Query (Lines 217-236)**
- Calls `fetch_slots()` for each (commodity_id, date) pair
- Handles three response states:
  - **NOT_OPEN** (lines 220-228): Booking not yet available despite being past open date
  - **ERROR** (lines 230-236): Network error or token expiration
  - **OK** (lines 238-276): Successfully retrieved ticket data

**Phase 3: Change Detection & Notification (Lines 239-276)**
- Formats available tickets into readable lines
- Compares with previous state:
  - **State Change**: `"NOT_OPEN"` → `"HAS_STOCK"` or `"NO_STOCK"`
  - **Payload Change**: Different available time slots
- Sends push notification only when changes are detected
- Updates `last_pushed` cache

**Phase 4: Adaptive Sleep (Lines 279-285)**
- **High-frequency mode**: `CHECK_INTERVAL_SEC + jitter` (when in booking window)
- **Low-frequency mode**: `EARLY_CHECK_INTERVAL_SEC + jitter` (before booking window)
- Logs sleep duration

### 8. Entry Point (Lines 287-288)

```python
if __name__ == "__main__":
    main()
```

Standard Python idiom to execute `main()` when script is run directly.

## Architecture Patterns

### 1. Stateless Design
The agent maintains **no persistent storage**:
- All state is kept in memory (`last_pushed` dictionary)
- Restarts require rebuilding state from API responses
- Simplifies deployment and reduces I/O overhead

### 2. Change-Driven Notifications
The agent implements a **push-on-change** strategy:
- Only sends notifications when ticket availability changes
- Prevents notification spam during stable periods
- Reduces Server酱 API usage costs

### 3. Adaptive Polling
Implements **dual-frequency polling**:
- **Low-frequency** (12 hours): Before booking window opens
- **High-frequency** (60 seconds): During active booking period
- Optimizes API usage while maintaining responsiveness

### 4. Robust Error Handling
Multiple layers of fault tolerance:
- **Network Layer**: Automatic retries with exponential backoff
- **API Layer**: Graceful degradation on errors
- **Notification Layer**: Failures don't interrupt monitoring
- **Logging**: All errors recorded for debugging

### 5. Configurable via Environment
Sensitive data (tokens, API keys) can be provided through:
- **`.env` file**: Local development (via `python-dotenv`)
- **Environment variables**: Production deployment
- **Fallback values**: In-code defaults for non-sensitive settings

## Data Flow

```
┌─────────────────┐
│  Configuration  │
│   (Lines 26-49) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Initialize Sess │
│  & Logging      │
│  (Lines 51-85)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Main Loop     │◄─────────┐
│ (Lines 198-285) │          │
└────────┬────────┘          │
         │                   │
         ▼                   │
┌─────────────────┐          │
│  Check if Open  │──No──────┤
│  (Lines 206-215)│          │
└────────┬────────┘          │
         │ Yes               │
         ▼                   │
┌─────────────────┐          │
│  Fetch Slots    │          │
│ (Lines 123-157) │          │
└────────┬────────┘          │
         │                   │
         ▼                   │
┌─────────────────┐          │
│ Format & Compare│          │
│ (Lines 159-174) │          │
└────────┬────────┘          │
         │                   │
         ▼                   │
┌─────────────────┐          │
│ Notify if Change│          │
│ (Lines 105-115) │          │
└────────┬────────┘          │
         │                   │
         ▼                   │
┌─────────────────┐          │
│ Adaptive Sleep  │          │
│ (Lines 279-285) │──────────┘
└─────────────────┘
```

## Dependencies

### External Libraries
- **`requests`**: HTTP client for API communication
- **`python-dotenv`**: Environment variable management
- **`urllib3`**: Retry logic for HTTP requests

### Standard Library
- **`os`**: Environment variable access
- **`time`**: Sleep functions
- **`random`**: Jitter generation
- **`datetime`**: Date/time calculations
- **`typing`**: Type hints
- **`logging`**: Structured logging

## Key Design Decisions

1. **In-Memory State**: Simplifies deployment but requires manual restart handling
2. **Dual Logging**: Both file and console for flexible monitoring
3. **Dynamic Token Loading**: Allows token refresh without restart
4. **15-Day Rule**: Hard-coded booking window calculation
5. **Random Jitter**: Prevents synchronized requests from multiple instances
6. **Markdown Support**: Server酱 notifications can use rich formatting (though currently simple text)

## Extension Points

The architecture allows for easy extensions:

1. **Multiple Notification Channels**: Add functions similar to `notify_serverchan()`
2. **Database Backend**: Replace `last_pushed` dict with persistent storage
3. **Web Interface**: Expose status via HTTP server
4. **Auto-Booking**: Add purchase API integration
5. **Multi-Venue**: Extend beyond Potala Palace with configuration
