# Logstor

## Introduction

Logstor is a log-structured storage engine for ScyllaDB optimized for key-value workloads. It provides an alternative storage backend for key-value tables - tables with a partition key only, with no clustering columns.

Unlike the traditional LSM-tree based storage, logstor uses a log-structured approach with in-memory indexing, making it particularly suitable for workloads with frequent overwrites and point lookups.

## Architecture

Logstor consists of several key components:

### Components

#### Primary Index

The primary index is entirely in memory and it maps a partition key to its location in the log segments. It consists of a B-tree per each table that is ordered token.

#### Segment Manager

The `segment_manager` handles the allocation and management of fixed-size segments (default 128KB). Segments are grouped into large files (default 32MB). Key responsibilities include:

- **Segment allocation**: Provides segments for writing new data
- **Space reclamation**: Tracks free space in each segment
- **Compaction**: Copies live data from sparse segments to reclaim space
- **Recovery**: Scans segments on startup to rebuild the index
- **Separator**: Rewrites segments that have records from different compaction groups into new segments that are separated by compaction group.

The data in the segments consists of records of type `log_record`. Each record contains the value for some key as a `canonical_mutation` and additional metadata.

The `segment_manager` receives new writes via a `write_buffer` and writes them sequentially to the active segment with 4k-block alignment.

#### Write Buffer

The `write_buffer` manages a buffer of log records and handles the serialization of the records including headers and alignment. It can be used to write multiple records to the buffer and then write the buffer to the segment manager.

The `buffered_writer` manages multiple write buffers for user writes, an active buffer and multiple flushing ones, to batch writes and manage backpressure.

### Data Flow

**Write Path:**
1. Application writes mutation to logstor
2. Mutation is converted to a log record
3. Record is written to write buffer
4. The buffer is switched and written to the active segment.
5. Index is updated with new record locations
6. Old record locations (for overwrites) are marked as free

**Read Path:**
1. Application requests data for a partition key
2. Index lookup returns record location
3. Segment manager reads record from disk
4. Record is deserialized into a mutation and returned

**Separator:**
1. When a record is written to the active segment, it is also written to its compaction group's separator buffer. The separator buffer holds a reference to the original segment.
2. The separator buffer is flushed when it's full, or requested to flush for other reason. It is written into a new segment in the compaction group, and it updates the location of the records from the original mixed segments to the new segments in the compaction group.
3. After the separator buffer is flushed and all records from the original segment are moved, it releases the reference of the segment. When there are no more reference to the segment it is freed.

**Compaction:**
1. The amount of live data is tracked for each segment in its segment_descriptor. The segment descriptors are stored in a histogram by live data.
2. A segment set from a single compaction group is submitted for compaction.
3. Compaction picks segments for compaction from the segment set. It chooses segments with the lowest utilization such that compacting them results in net gain of free segments.
4. It reads the segments, finding all live records, and writing them into a write buffer. When the buffer is full it is flushed into a new segment, and for each recording updating the index location to the new location.
5. After all live records are rewritten the old segments are freed.

## Usage

### Enabling Logstor

To use logstor, enable it in the configuration:

```yaml
enable_logstor: true

experimental_features:
  - logstor
```

### Creating Tables

Tables using logstor must have no clustering columns, and created with the `storage_engine` property equals to 'logstor':

```cql
CREATE TABLE keyspace.user_profiles (
    user_id uuid PRIMARY KEY,
    name text,
    email text,
    metadata frozen<map<text, text>>
) WITH storage_engine = 'logstor';
```

### Basic Operations

**Insert/Update:**

```cql
INSERT INTO keyspace.table_name (pk, v) VALUES (1, 'value1');
INSERT INTO keyspace.table_name (pk, v) VALUES (2, 'value2');

-- Overwrite with new value
INSERT INTO keyspace.table_name (pk, v) VALUES (1, 'updated_value');
```

Currently, updates must write the full row. Updating individual columns is not yet supported. Each write replaces the entire partition.

**Select:**

```cql
SELECT * FROM keyspace.table_name WHERE pk = 1;
-- Returns: (1, 'updated_value')

SELECT pk, v FROM keyspace.table_name WHERE pk = 2;
-- Returns: (2, 'value2')

SELECT * FROM keyspace.table_name;
-- Returns: (1, 'updated_value'), (2, 'value2')
```

**Delete:**

```cql
DELETE FROM keyspace.table_name WHERE pk = 1;
```
