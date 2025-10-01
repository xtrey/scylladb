#
# Copyright (C) 2024-present ScyllaDB
#
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.0
#
import pytest
import logging
import time

from cassandra.cluster import ConsistencyLevel

from test.pylib.manager_client import ManagerClient
from test.pylib.scylla_cluster import ReplaceConfig
from test.pylib.util import wait_for_cql_and_get_hosts
from test.cluster.util import check_node_log_for_failed_mutations, start_writes


@pytest.mark.asyncio
@pytest.mark.parametrize('tablets_enabled', [True, False])
@pytest.mark.max_running_servers(amount=5)
async def test_zero_token_nodes_topology_ops(manager: ManagerClient, tablets_enabled: bool):
    """
    Test that:
    - adding a zero-token node in the gossip-based topology fails
    - topology operations in the Raft-based topology involving zero-token nodes succeed
    - client requests to normal nodes in the presence of zero-token nodes (2 normal nodes, RF=2, CL=2) succeed
    """

    def get_pf(rack: str) -> dict[str, str]:
        return {"dc": "dc1", "rack": rack}

    logging.info('Trying to add a zero-token server in the gossip-based topology')
    await manager.server_add(config={'join_ring': False,
                                     'force_gossip_topology_changes': True,
                                     'tablets_mode_for_new_keyspaces': 'disabled'},
                             property_file=get_pf("rz"),
                             expected_error='the raft-based topology is disabled')

    normal_cfg = {'tablets_mode_for_new_keyspaces': 'enabled' if tablets_enabled else 'disabled'}
    zero_token_cfg = {'tablets_mode_for_new_keyspaces': 'enabled' if tablets_enabled else 'disabled', 'join_ring': False}

    logging.info('Adding the first server')
    server_a = await manager.server_add(config=normal_cfg, property_file=get_pf("r1"))

    logging.info('Adding the second server as zero-token')
    server_b = await manager.server_add(config=zero_token_cfg, property_file=get_pf("rz"))

    logging.info('Adding the third server')
    server_c = await manager.server_add(config=normal_cfg, property_file=get_pf("r2"))

    await wait_for_cql_and_get_hosts(manager.cql, [server_a, server_c], time.time() + 60)
    finish_writes = await start_writes(manager.cql, 2, ConsistencyLevel.TWO)

    logging.info('Adding the fourth server as zero-token')
    await manager.server_add(config=zero_token_cfg, property_file=get_pf("rz"))  # Necessary to preserve the Raft majority.

    logging.info(f'Restarting {server_b}')
    await manager.server_stop_gracefully(server_b.server_id)
    await manager.server_start(server_b.server_id)

    logging.info(f'Stopping {server_b}')
    await manager.server_stop_gracefully(server_b.server_id)

    replace_cfg_b = ReplaceConfig(replaced_id=server_b.server_id, reuse_ip_addr=False, use_host_id=False)
    logging.info(f'Trying to replace {server_b} with a token-owing server')
    await manager.server_add(replace_cfg_b, config=normal_cfg, property_file=server_b.property_file(),
                             expected_error='Cannot replace the zero-token node')

    logging.info(f'Replacing {server_b}')
    server_b = await manager.server_add(replace_cfg_b, config=zero_token_cfg, property_file=server_b.property_file())

    logging.info(f'Stopping {server_b}')
    await manager.server_stop_gracefully(server_b.server_id)

    replace_cfg_b = ReplaceConfig(replaced_id=server_b.server_id, reuse_ip_addr=True, use_host_id=False)
    logging.info(f'Replacing {server_b} with the same IP')
    server_b = await manager.server_add(replace_cfg_b, config=zero_token_cfg, property_file=server_b.property_file())

    logging.info(f'Decommissioning {server_b}')
    await manager.decommission_node(server_b.server_id)

    logging.info('Adding two zero-token servers')
    [server_b, server_d] = await manager.servers_add(2, config=zero_token_cfg, property_file=get_pf("rz"))

    logging.info(f'Rebuilding {server_b}')
    await manager.rebuild_node(server_b.server_id)

    logging.info(f'Stopping {server_b}')
    await manager.server_stop_gracefully(server_b.server_id)

    logging.info(f'Stopping {server_d}')
    await manager.server_stop_gracefully(server_d.server_id)

    server_d_id = await manager.get_host_id(server_d.server_id)
    logging.info(f'Initiating removenode of {server_b} by {server_a}, ignore_dead={[server_d_id]}')
    await manager.remove_node(server_a.server_id, server_b.server_id, [server_d_id])

    logging.info(f'Initiating removenode of {server_d} by {server_a}')
    await manager.remove_node(server_a.server_id, server_d.server_id)

    logging.info('Adding a zero-token server')
    await manager.server_add(config=zero_token_cfg, property_file=get_pf("rz"))

    # FIXME: Finish writes after the last server_add call once scylladb/scylladb#19737 is fixed.
    logging.info('Checking results of the background writes')
    await finish_writes()

    logging.info('Adding a normal server')
    server_e = await manager.server_add(config=normal_cfg, property_file=get_pf("r1"))

    logging.info(f'Stopping {server_e}')
    await manager.server_stop_gracefully(server_e.server_id)

    replace_cfg_e = ReplaceConfig(replaced_id=server_e.server_id, reuse_ip_addr=False, use_host_id=False)
    logging.info(f'Trying to replace {server_e} with a zero-token server')
    await manager.server_add(replace_cfg_e, config=zero_token_cfg, property_file=server_e.property_file(),
                             expected_error='Cannot replace the token-owning node')

    await check_node_log_for_failed_mutations(manager, server_a)
    await check_node_log_for_failed_mutations(manager, server_c)
