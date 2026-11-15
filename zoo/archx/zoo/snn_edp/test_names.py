"""Every operation has one explicit role and one unambiguous physical owner."""
from snn_edp import model


def test_operation_names_and_roles_have_single_owners():
    hardware=model.load(model.HERE/'hardware.json')
    aliases=model.load(model.HERE/'provenance/operation_renames.json')['operation_keys']
    assert not set(aliases).intersection(hardware)
    assert set(aliases.values())<=hardware.keys()
    events={};physical_roles={}
    for key,spec in hardware.items():
        assert spec['role'].strip()
        owner=model.physical(key,spec)
        assert physical_roles.setdefault(owner,spec['role'])==spec['role']
        for arm in model.ARMS:
            name=model.event(arm,key)
            assert name not in events
            events[name]=owner
            assert name.startswith(arm+'__'+key.split('.')[0]+'__')
    assert len(events)==3*len(hardware)


def test_characterization_recipes_use_the_same_operation_names():
    import yaml
    hardware=model.load(model.HERE/'hardware.json')
    aliases=model.load(model.HERE/'provenance/operation_renames.json')['operation_keys']
    for key in aliases.values():
        arch,module,operation=key.split('.')
        recipe=yaml.safe_load((model.HERE/f'characterization/{arch}.architecture.yaml').read_text())
        spec=recipe['architecture']['module'][module]
        assert str(spec['operations'][operation])==hardware[key]['count_expression']
        assert spec['query']['class']==hardware[key]['query']['class']


def test_compiled_operation_events_have_exactly_the_declared_module_child():
    for arch in model.ARCHES:
        root=model.HERE/'runs'/arch/'fixture_counts'
        manifest=model.load(root/'manifest.json')
        for arm in model.ARMS:
            graph=model.load(root/manifest['graphs'][arm])
            for key,spec in model.operations(arch,arm).items():
                namespace,module,operation=key.split('.')
                source=f'{arm}__{namespace}__{module}__{operation}'
                edges=[e for e in graph['edges'] if e['source']==source]
                edge,=edges
                assert edge['target']==f"m__{namespace}__{spec.get('physical_module',module)}"
                assert edge['operation']=={'dynamic_energy':operation}


def test_table_identity_fields_match_every_operation_key():
    for filename in ('energy_table.json','characterization/energy_table_dummy.json'):
        table=model.load(model.HERE/filename)
        assert set(table)==set(model.load(model.HERE/'hardware.json'))
        for key,row in table.items():
            arch,module,operation=key.split('.')
            assert (row['module'],row['operation'])==(module,operation), (filename,key)
