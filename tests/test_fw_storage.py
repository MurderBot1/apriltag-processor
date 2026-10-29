"""Persistent storage of calibration + field map: two alternating flash slots, sequence numbers, CRC, power-loss safety."""
import os
import random
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwutil                      # noqa: E402
from fwutil import Dev, P, simfw   # noqa: E402

DEFAULT_CAL = (640.0, 640.0, 639.5, 399.5, 0, 0, 0, 0, 0)


def committed_dev(configs, flash=None):
    """Device with each (cal, tags) committed in turn."""
    d = Dev(fw=simfw.NativeFirmware(flash=flash)) if flash else Dev()
    for cal, tags in configs:
        d.set_config(cal, tags, commit=True)
    return d


def cfg_bytes(cal, tags):
    return fwutil.cal_body(cal), [fwutil.tag_body(t) for t in tags]


def test_fresh_device_has_default_calibration_and_empty_map():
    d = Dev()
    cfg, tags = d.dump()
    assert struct.unpack_from('<9f', cfg) == DEFAULT_CAL and tags == []
    assert d.fw.stats()['store_seq'] == 0


def test_roundtrip_repo_config_and_reboot():
    cal, tmap = fwutil.load_json('config/camera_calibration.json'), fwutil.load_json('config/tag_map.json')['tags']
    d = Dev()
    d.set_config(cal, tmap, commit=True)
    before = d.dump()
    d.reboot()
    after = d.dump()
    assert fwutil.close_dump(before, after)
    assert len(after[1]) == len(tmap)
    # values are the ones we sent (float32 precision)
    c = struct.unpack_from('<9f', after[0])
    assert c[0] == pytest.approx(cal['fx'], rel=1e-6) and c[4] == pytest.approx(cal['dist'][0], rel=1e-6)
    assert d.fw.stats()['store_seq'] == 1


@pytest.mark.parametrize('ntags', [0, 1, 2, 17, 63, 64])
def test_roundtrip_random_maps(ntags):
    rng = random.Random(100 + ntags)
    cal, tags = fwutil.rand_cal(rng), fwutil.rand_tags(rng, ntags)
    d = Dev()
    d.set_config(cal, tags, commit=True)
    ram = d.dump()
    d.reboot()
    assert fwutil.close_dump(ram, d.dump())
    # id order and exact positions survive
    ids = [struct.unpack_from('<H', t)[0] for t in d.dump()[1]]
    assert ids == [t['id'] for t in tags]


def test_slots_alternate_and_seq_increments():
    rng = random.Random(3)
    d = Dev()
    seen = []
    for i in range(1, 7):
        d.set_config(fwutil.rand_cal(rng), fwutil.rand_tags(rng, 3), commit=True)
        parsed = [fwutil.stored_slot(s) for s in d.flash.slots]
        seen.append(parsed)
        assert d.fw.stats()['store_seq'] == i
        newest_slot = i & 1
        assert parsed[newest_slot] is not None and parsed[newest_slot][0] == i
        if i > 1:
            assert parsed[newest_slot ^ 1][0] == i - 1          # the other slot still holds the previous commit


def test_highest_seq_wins_after_reboot_even_with_stale_other_slot():
    rng = random.Random(4)
    cfgs = [(fwutil.rand_cal(rng), fwutil.rand_tags(rng, 5 + i)) for i in range(4)]
    d = committed_dev(cfgs)
    d.reboot()
    assert fwutil.close_dump(d.dump(), _ram_dump_of(cfgs[-1]))
    # next commit continues the sequence
    d.set_config(*cfgs[0], commit=True)
    assert d.fw.stats()['store_seq'] == 5


def _ram_dump_of(cfg):
    d = Dev()
    d.set_config(*cfg)
    return d.dump()


def test_crafted_slots_pick_highest_seq_regardless_of_position():
    cvals = (500, 501, 300.5, 200.5, 0.1, 0.01, 0, 0, 0)
    q = (1.0, 0, 0, 0)
    f = simfw.FakeFlash()
    f.slots[0][:] = fwutil.pack_slot(10, cvals, [(7, 0.1, (1, 2, 3), q)])
    f.slots[1][:] = fwutil.pack_slot(3, (600,) * 4 + (0,) * 5, [(8, 0.2, (0, 0, 0), q), (9, 0.2, (0, 0, 0), q)])
    d = Dev(fw=simfw.NativeFirmware(flash=f))
    cfg, tags = d.dump()
    assert struct.unpack_from('<4f', cfg)[0] == 500 and len(tags) == 1 and d.fw.stats()['store_seq'] == 10
    f2 = simfw.FakeFlash()
    f2.slots[0][:] = fwutil.pack_slot(2, cvals, [(7, 0.1, (1, 2, 3), q)])
    f2.slots[1][:] = fwutil.pack_slot(9, (600,) * 4 + (0,) * 5, [(8, 0.2, (0, 0, 0), q)])
    d = Dev(fw=simfw.NativeFirmware(flash=f2))
    assert struct.unpack_from('<4f', d.dump()[0])[0] == 600 and d.fw.stats()['store_seq'] == 9


def test_crc_corrupted_newest_slot_falls_back_to_previous():
    rng = random.Random(5)
    old, new = (fwutil.rand_cal(rng), fwutil.rand_tags(rng, 6)), (fwutil.rand_cal(rng), fwutil.rand_tags(rng, 9))
    d = committed_dev([old, new])
    newest = fwutil.stored_slot(d.flash.slots[0])      # seq 2 lives in slot 0
    assert newest[0] == 2
    used = len(newest[1])
    ref_old = _ram_dump_of(old)
    for pos in list(range(0, used)) + [used - 1]:       # flip one bit in every used byte of the newest slot
        saved = d.flash.slots[0][pos]
        d.flash.slots[0][pos] ^= 0x10
        d.reboot()
        assert fwutil.close_dump(d.dump(), ref_old), pos
        assert d.fw.stats()['store_seq'] == 1
        d.flash.slots[0][pos] = saved
    d.reboot()
    assert d.fw.stats()['store_seq'] == 2


def test_both_slots_corrupt_gives_defaults():
    d = committed_dev([(fwutil.load_json('config/camera_calibration.json'), fwutil.load_json('config/tag_map.json')['tags'])] * 2)
    for s in d.flash.slots:
        s[20] ^= 0xFF
    d.reboot()
    cfg, tags = d.dump()
    assert tags == [] and struct.unpack_from('<9f', cfg) == DEFAULT_CAL and d.fw.stats()['store_seq'] == 0


def test_erased_flash_and_garbage_flash():
    d = Dev(fw=simfw.NativeFirmware(flash=simfw.FakeFlash()))
    assert d.dump()[1] == []
    f = simfw.FakeFlash()
    rng = random.Random(6)
    for s in f.slots:
        s[:] = bytes(rng.randrange(256) for _ in range(simfw.SLOT_BYTES))
    d = Dev(fw=simfw.NativeFirmware(flash=f))
    assert d.dump()[1] == [] and d.fw.stats()['store_seq'] == 0
    f = simfw.FakeFlash()
    for s in f.slots:
        s[:] = bytes(simfw.SLOT_BYTES)                       # all zeros
    assert Dev(fw=simfw.NativeFirmware(flash=f)).dump()[1] == []


def test_wrong_magic_ignored_even_with_valid_crc():
    q = (1.0, 0, 0, 0)
    f = simfw.FakeFlash()
    f.slots[0][:] = fwutil.pack_slot(5, (500,) * 4 + (0,) * 5, [(7, 0.1, (1, 2, 3), q)], magic=0x31465442)
    f.slots[1][:] = fwutil.pack_slot(4, (700,) * 4 + (0,) * 5, [(7, 0.1, (1, 2, 3), q)])
    d = Dev(fw=simfw.NativeFirmware(flash=f))
    assert struct.unpack_from('<f', d.dump()[0])[0] == 700 and d.fw.stats()['store_seq'] == 4


def test_invalid_ntags_or_bad_crc_ignored():
    q = (1.0, 0, 0, 0)
    base = (500,) * 4 + (0,) * 5
    f = simfw.FakeFlash()
    f.slots[0][:] = fwutil.pack_slot(9, base, [(7, 0.1, (1, 2, 3), q)], ntags_field=65)          # too many tags
    f.slots[1][:] = fwutil.pack_slot(8, base, [(7, 0.1, (1, 2, 3), q)], fix_crc=False)             # wrong CRC
    assert Dev(fw=simfw.NativeFirmware(flash=f)).dump()[1] == []
    f.slots[0][:] = fwutil.pack_slot(9, base, [(7, 0.1, (1, 2, 3), q)], ntags_field=0xFFFF)
    assert Dev(fw=simfw.NativeFirmware(flash=f)).dump()[1] == []


def test_commit_failure_paths_keep_previous_config():
    rng = random.Random(7)
    a, b = (fwutil.rand_cal(rng), fwutil.rand_tags(rng, 4)), (fwutil.rand_cal(rng), fwutil.rand_tags(rng, 8))
    d = committed_dev([a])
    ref = _ram_dump_of(a)
    d.set_config(*b)
    # erase / program failure
    d.flash.power_cut_after = d.flash.ops + 10
    assert d.nak(P.CMD_COMMIT) == P.ERR_FLASH
    d.flash.dead = False
    d.flash.power_cut_after = None
    d.reboot()
    assert fwutil.close_dump(d.dump(), ref)
    # silent write corruption must be caught by the read-back verify
    d.set_config(*b)
    d.flash.write_corrupt = True
    assert d.nak(P.CMD_COMMIT) == P.ERR_FLASH
    d.flash.write_corrupt = False
    d.reboot()
    assert fwutil.close_dump(d.dump(), ref)
    # and a retry with a healthy flash succeeds
    d.set_config(*b, commit=True)
    d.reboot()
    assert fwutil.close_dump(d.dump(), _ram_dump_of(b))


def test_uncommitted_changes_are_lost_on_reboot():
    rng = random.Random(8)
    a, b = (fwutil.rand_cal(rng), fwutil.rand_tags(rng, 4)), (fwutil.rand_cal(rng), fwutil.rand_tags(rng, 8))
    d = committed_dev([a])
    d.set_config(*b)
    d.reboot()
    assert fwutil.close_dump(d.dump(), _ram_dump_of(a))


# ------------------------------------------------------------------------------ power loss during commit
def _power_loss_sweep(setup, new_cfg, torn):
    """Cut power after k byte-operations of the commit, for EVERY k in [0, total]; the flash must always load either the
    previously committed configuration or the new one, bit-exact, never a mix."""
    rng_cfgs = setup
    base = committed_dev(rng_cfgs)
    snapshot = [bytes(s) for s in base.flash.slots]
    old_slot = max((fwutil.stored_slot(s) for s in snapshot if fwutil.stored_slot(s)), key=lambda x: x[0], default=None)
    old_payload = old_slot[1] if old_slot else None
    old_seq = old_slot[0] if old_slot else 0
    old_ref = _ram_dump_of(rng_cfgs[-1]) if rng_cfgs else None

    # dry run to learn the total number of byte operations and the new payload
    probe = Dev(fw=simfw.NativeFirmware(flash=_flash_from(snapshot)))
    probe.set_config(*new_cfg)
    probe.fw.flash.ops = 0
    probe.ok(P.CMD_COMMIT)
    total = probe.fw.flash.ops
    new_slot = max((fwutil.stored_slot(s) for s in probe.fw.flash.slots if fwutil.stored_slot(s)), key=lambda x: x[0])
    new_payload = new_slot[1]
    new_ref = _ram_dump_of(new_cfg)
    assert new_slot[0] == old_seq + 1 and total >= 4096 + 50
    assert old_payload != new_payload

    dev = Dev(fw=simfw.NativeFirmware(flash=_flash_from(snapshot)))
    dev.set_config(*new_cfg)                        # RAM state: the new config, about to be committed
    store_seq_before = dev.fw.stats()['store_seq']
    n_new = n_old = 0
    loader = Dev()
    for k in range(total + 1):
        f = dev.fw.flash
        for i in range(2):
            f.slots[i][:] = snapshot[i]
        f.dead, f.ops, f.power_cut_after, f.torn_byte = False, 0, k, torn
        r = dev.send(P.CMD_COMMIT)
        survived = r == [(P.RSP_ACK, bytes([P.CMD_COMMIT]))]
        assert survived == (k >= total), k
        # --- reboot from the frozen flash contents with a separate firmware instance
        frozen = loader.fw.flash
        for i in range(2):
            frozen.slots[i][:] = f.slots[i]
        chosen = [fwutil.stored_slot(s) for s in frozen.slots]
        chosen = max((c for c in chosen if c), key=lambda x: x[0], default=None)
        payload = chosen[1] if chosen else None
        assert payload in (old_payload, new_payload), ('mixed/unknown config after cut at', k)
        want_new = payload == new_payload
        if survived:
            assert want_new
        if k < total - 1:
            assert not want_new, k                 # the new config only becomes visible once (essentially) every byte is in
        n_new += want_new
        n_old += not want_new
        loader.fw.boot()
        st = loader.fw.stats()
        assert st['store_seq'] == (chosen[0] if chosen else 0), k
        if k % 97 == 0 or k >= total - 2 or k in (0, 1, 4095, 4096, 4097):
            d2 = loader
            ref = new_ref if want_new else (old_ref if old_ref else _empty_dump())
            assert fwutil.close_dump(d2.dump(), ref), k
        if survived:
            dev.fw.boot()
            dev.set_config(*new_cfg)
            dev.fw.flash.slots[0][:] = snapshot[0]
            dev.fw.flash.slots[1][:] = snapshot[1]
        if dev.fw.stats()['store_seq'] != store_seq_before:      # (only after a successful commit) restore the RAM app state
            dev.fw.boot()
            dev.set_config(*new_cfg)
    assert n_old > 0 and n_new >= 1
    return total


def _empty_dump():
    return Dev().dump()


def _flash_from(snapshot):
    f = simfw.FakeFlash()
    for i in range(2):
        f.slots[i][:] = snapshot[i]
    return f


def _small(seed, n):
    rng = random.Random(seed)
    return fwutil.rand_cal(rng), fwutil.rand_tags(rng, n)


@pytest.mark.parametrize('torn', [False, True], ids=['clean-cut', 'torn-byte'])
def test_power_loss_first_ever_commit(torn):
    total = _power_loss_sweep([], _small(21, 64), torn)
    assert total == 4096 + 12 + 36 + 64 * 36 + 2


@pytest.mark.parametrize('torn', [False, True], ids=['clean-cut', 'torn-byte'])
def test_power_loss_second_commit_one_populated_slot(torn):
    _power_loss_sweep([_small(22, 64)], _small(23, 64), torn)


@pytest.mark.parametrize('torn', [False, True], ids=['clean-cut', 'torn-byte'])
def test_power_loss_third_commit_both_slots_populated(torn):
    _power_loss_sweep([_small(24, 10), _small(25, 64)], _small(26, 30), torn)


def test_power_loss_small_map_overwriting_bigger_old_slot():
    _power_loss_sweep([_small(27, 64), _small(28, 64)], _small(29, 0), False)


def test_flash_ops_are_erase_then_program_only_in_target_slot():
    """The slot holding the newest valid config is never touched while committing."""
    d = committed_dev([_small(31, 5), _small(32, 5)])
    newest = max(range(2), key=lambda i: fwutil.stored_slot(d.flash.slots[i])[0])
    before = bytes(d.flash.slots[newest])
    d.set_config(*_small(33, 5))
    touched = []
    orig_e, orig_w = d.flash.erase, d.flash.write
    d.flash.erase = lambda s: (touched.append(s), orig_e(s))[1]
    d.flash.write = lambda s, o, b: (touched.append(s), orig_w(s, o, b))[1]
    d.ok(P.CMD_COMMIT)
    assert set(touched) == {newest ^ 1}
    assert bytes(d.flash.slots[newest]) == before
