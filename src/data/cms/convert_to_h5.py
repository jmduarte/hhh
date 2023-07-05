import logging
from pathlib import Path

import awkward as ak
import click
import h5py
import numpy as np
import uproot
import vector
from coffea.nanoevents import BaseSchema, NanoEventsFactory

vector.register_awkward()

logging.basicConfig(level=logging.INFO)

N_JETS = 10
N_FJETS = 3
N_MASSES = 45
MIN_JET_PT = 20
MIN_FJET_PT = 200
MIN_JETS = 6
MIN_MASS = 50
PROJECT_DIR = Path(__file__).resolve().parents[3]


def get_n_features(name, events, iterator):
    if name.format(i=iterator[0]) not in dir(events):
        logging.warning(f"Variable {name.format(i=iterator[0])} does not exist in tree; returning all 0s")
        return ak.from_numpy(np.zeros((len(events), len(iterator))))
    return ak.concatenate(
        [np.expand_dims(events[name.format(i=i)], axis=-1) for i in iterator],
        axis=-1,
    )


def get_datasets(events):
    # small-radius jet info
    pt = get_n_features("jet{i}Pt", events, range(1, N_JETS + 1))
    ptcorr = get_n_features("jet{i}PtCorr", events, range(1, N_JETS + 1))
    eta = get_n_features("jet{i}Eta", events, range(1, N_JETS + 1))
    phi = get_n_features("jet{i}Phi", events, range(1, N_JETS + 1))
    btag = get_n_features("jet{i}DeepFlavB", events, range(1, N_JETS + 1))
    jet_id = get_n_features("jet{i}JetId", events, range(1, N_JETS + 1))
    higgs_idx = get_n_features("jet{i}HiggsMatchedIndex", events, range(1, N_JETS + 1))
    hadron_flavor = get_n_features("jet{i}HadronFlavour", events, range(1, N_JETS + 1))
    matched_fj_idx = get_n_features("jet{i}FatJetMatchedIndex", events, range(1, N_JETS + 1))
    inv_mass = get_n_features("jet{i}Mass", events, range(1, N_JETS + 1))

    # paired masses
    mass = get_n_features("mass{i}", events, range(N_MASSES))

    # large-radius jet info
    fj_pt = get_n_features("fatJet{i}Pt", events, range(1, N_FJETS + 1))
    fj_eta = get_n_features("fatJet{i}Eta", events, range(1, N_FJETS + 1))
    fj_phi = get_n_features("fatJet{i}Phi", events, range(1, N_FJETS + 1))
    fj_mass = get_n_features("fatJet{i}Mass", events, range(1, N_FJETS + 1))
    fj_sdmass = get_n_features("fatJet{i}MassSD", events, range(1, N_FJETS + 1))
    fj_regmass = get_n_features("fatJet{i}MassRegressed", events, range(1, N_FJETS + 1))
    fj_nsub = get_n_features("fatJet{i}NSubJets", events, range(1, N_FJETS + 1))
    fj_tau32 = get_n_features("fatJet{i}Tau3OverTau2", events, range(1, N_FJETS + 1))
    fj_xbb = get_n_features("fatJet{i}PNetXbb", events, range(1, N_FJETS + 1))
    fj_xqq = get_n_features("fatJet{i}PNetXjj", events, range(1, N_FJETS + 1))
    fj_qcd = get_n_features("fatJet{i}PNetQCD", events, range(1, N_FJETS + 1))
    fj_higgs_idx = get_n_features("fatJet{i}HiggsMatchedIndex", events, range(1, N_FJETS + 1))

    # keep events with >= MIN_JETS small-radius jets
    mask = ak.num(pt[pt > MIN_JET_PT]) >= MIN_JETS
    pt = pt[mask]
    ptcorr = ptcorr[mask]
    eta = eta[mask]
    phi = phi[mask]
    btag = btag[mask]
    mass = mass[mask]
    jet_id = jet_id[mask]
    higgs_idx = higgs_idx[mask]
    hadron_flavor = hadron_flavor[mask]
    matched_fj_idx = matched_fj_idx[mask]
    inv_mass = inv_mass[mask]

    mass = mass[mask]

    fj_pt = fj_pt[mask]
    fj_eta = fj_eta[mask]
    fj_phi = fj_phi[mask]
    fj_mass = fj_mass[mask]
    fj_sdmass = fj_sdmass[mask]
    fj_regmass = fj_regmass[mask]
    fj_nsub = fj_nsub[mask]
    fj_tau32 = fj_tau32[mask]
    fj_xbb = fj_xbb[mask]
    fj_xqq = fj_xqq[mask]
    fj_qcd = fj_qcd[mask]
    fj_higgs_idx = fj_higgs_idx[mask]

    # mask to define zero-padded small-radius jets
    mask = pt > MIN_JET_PT
    mask_mass = mass > MIN_MASS

    # mask to define zero-padded large-radius jets
    fj_mask = fj_pt > MIN_FJET_PT

    # require hadron_flavor == 5 (i.e. b-jet ghost association matching)
    higgs_idx = ak.where(higgs_idx != 0, ak.where(hadron_flavor == 5, higgs_idx, -1), 0)

    # index of small-radius jet if Higgs is reconstructed
    h1_bs = ak.local_index(higgs_idx)[higgs_idx == 1]
    h2_bs = ak.local_index(higgs_idx)[higgs_idx == 2]
    h3_bs = ak.local_index(higgs_idx)[higgs_idx == 3]

    # index of large-radius jet if Higgs is reconstructed
    h1_bb = ak.local_index(fj_higgs_idx)[fj_higgs_idx == 1]
    h2_bb = ak.local_index(fj_higgs_idx)[fj_higgs_idx == 2]
    h3_bb = ak.local_index(fj_higgs_idx)[fj_higgs_idx == 3]

    # check/fix small-radius jet truth (ensure max 2 small-radius jets per higgs)
    check = (
        np.unique(ak.count(h1_bs, axis=-1)).to_list()
        + np.unique(ak.count(h2_bs, axis=-1)).to_list()
        + np.unique(ak.count(h3_bs, axis=-1)).to_list()
    )
    if 3 in check:
        logging.warning("some Higgs bosons match to 3 small-radius jets! Check truth")

    # check/fix large-radius jet truth (ensure max 1 large-radius jet per higgs)
    fj_check = (
        np.unique(ak.count(h1_bb, axis=-1)).to_list()
        + np.unique(ak.count(h2_bb, axis=-1)).to_list()
        + np.unique(ak.count(h3_bb, axis=-1)).to_list()
    )
    if 2 in fj_check:
        logging.warning("some Higgs bosons match to 2 large-radius jets! Check truth")

    h1_bs = ak.fill_none(ak.pad_none(h1_bs, 2, clip=True), -1)
    h2_bs = ak.fill_none(ak.pad_none(h2_bs, 2, clip=True), -1)
    h3_bs = ak.fill_none(ak.pad_none(h3_bs, 2, clip=True), -1)

    h1_bb = ak.fill_none(ak.pad_none(h1_bb, 1, clip=True), -1)
    h2_bb = ak.fill_none(ak.pad_none(h2_bb, 1, clip=True), -1)
    h3_bb = ak.fill_none(ak.pad_none(h3_bb, 1, clip=True), -1)

    h1_b1, h1_b2 = h1_bs[:, 0], h1_bs[:, 1]
    h2_b1, h2_b2 = h2_bs[:, 0], h2_bs[:, 1]
    h3_b1, h3_b2 = h3_bs[:, 0], h3_bs[:, 1]

    # mask whether Higgs can be reconstructed as 2 small-radius jet
    h1_mask = ak.all(h1_bs != -1, axis=-1)
    h2_mask = ak.all(h2_bs != -1, axis=-1)
    h3_mask = ak.all(h3_bs != -1, axis=-1)

    # mask whether Higgs can be reconstructed as 1 large-radius jet
    h1_fj_mask = ak.all(h1_bb != -1, axis=-1)
    h2_fj_mask = ak.all(h2_bb != -1, axis=-1)
    h3_fj_mask = ak.all(h3_bb != -1, axis=-1)

    datasets = {}
    datasets["INPUTS/Jets/MASK"] = mask.to_numpy()
    datasets["INPUTS/Jets/pt"] = pt.to_numpy()
    datasets["INPUTS/Jets/ptcorr"] = ptcorr.to_numpy()
    datasets["INPUTS/Jets/eta"] = eta.to_numpy()
    datasets["INPUTS/Jets/phi"] = phi.to_numpy()
    datasets["INPUTS/Jets/sinphi"] = np.sin(phi.to_numpy())
    datasets["INPUTS/Jets/cosphi"] = np.cos(phi.to_numpy())
    datasets["INPUTS/Jets/btag"] = btag.to_numpy()
    datasets["INPUTS/Jets/mass"] = mass.to_numpy()
    datasets["INPUTS/Jets/jetid"] = jet_id.to_numpy()
    datasets["INPUTS/Jets/matchedfj"] = matched_fj_idx.to_numpy()
    datasets["INPUTS/Jets/invmass"] = inv_mass.to_numpy()

    datasets["INPUTS/BoostedJets/MASK"] = fj_mask.to_numpy()
    datasets["INPUTS/BoostedJets/fj_pt"] = fj_pt.to_numpy()
    datasets["INPUTS/BoostedJets/fj_eta"] = fj_eta.to_numpy()
    datasets["INPUTS/BoostedJets/fj_phi"] = fj_phi.to_numpy()
    datasets["INPUTS/BoostedJets/fj_sinphi"] = np.sin(fj_phi.to_numpy())
    datasets["INPUTS/BoostedJets/fj_cosphi"] = np.cos(fj_phi.to_numpy())
    datasets["INPUTS/BoostedJets/fj_mass"] = fj_mass.to_numpy()
    datasets["INPUTS/BoostedJets/fj_sdmass"] = fj_sdmass.to_numpy()
    datasets["INPUTS/BoostedJets/fj_regmass"] = fj_regmass.to_numpy()
    datasets["INPUTS/BoostedJets/fj_nsub"] = fj_nsub.to_numpy()
    datasets["INPUTS/BoostedJets/fj_tau32"] = fj_tau32.to_numpy()
    datasets["INPUTS/BoostedJets/fj_xbb"] = fj_xbb.to_numpy()
    datasets["INPUTS/BoostedJets/fj_xqq"] = fj_xqq.to_numpy()
    datasets["INPUTS/BoostedJets/fj_qcd"] = fj_qcd.to_numpy()

    for i in range(0, N_MASSES):
        datasets[f"INPUTS/Masses/MASK{i}"] = mask_mass.to_numpy()[:, i]
        datasets[f"INPUTS/Masses/mass{i}"] = mass.to_numpy()[:, i]

    datasets["TARGETS/h1/mask"] = h1_mask.to_numpy()
    datasets["TARGETS/h1/b1"] = h1_b1.to_numpy()
    datasets["TARGETS/h1/b2"] = h1_b2.to_numpy()

    datasets["TARGETS/h2/mask"] = h2_mask.to_numpy()
    datasets["TARGETS/h2/b1"] = h2_b1.to_numpy()
    datasets["TARGETS/h2/b2"] = h2_b2.to_numpy()

    datasets["TARGETS/h3/mask"] = h3_mask.to_numpy()
    datasets["TARGETS/h3/b1"] = h3_b1.to_numpy()
    datasets["TARGETS/h3/b2"] = h3_b2.to_numpy()

    datasets["TARGETS/bh1/mask"] = h1_fj_mask.to_numpy()
    datasets["TARGETS/bh1/bb"] = h1_bb.to_numpy().reshape(h1_fj_mask.to_numpy().shape)

    datasets["TARGETS/bh2/mask"] = h2_fj_mask.to_numpy()
    datasets["TARGETS/bh2/bb"] = h2_bb.to_numpy().reshape(h2_fj_mask.to_numpy().shape)

    datasets["TARGETS/bh3/mask"] = h3_fj_mask.to_numpy()
    datasets["TARGETS/bh3/bb"] = h3_bb.to_numpy().reshape(h3_fj_mask.to_numpy().shape)

    return datasets


@click.command()
@click.argument("in-files", nargs=-1)
@click.option("--out-file", default=f"{PROJECT_DIR}/data/cms/hhh_training.h5", help="Output file.")
@click.option("--train-frac", default=0.95, help="Fraction for training.")
def main(in_files, out_file, train_frac):
    all_datasets = {}
    for file_name in in_files:
        with uproot.open(file_name) as in_file:
            num_entries = in_file["Events"].num_entries
            if "training" in out_file:
                entry_start = None
                entry_stop = int(train_frac * num_entries)
            else:
                entry_start = int(train_frac * num_entries)
                entry_stop = None
            events = NanoEventsFactory.from_root(
                in_file,
                treepath="Events",
                entry_start=entry_start,
                entry_stop=entry_stop,
                schemaclass=BaseSchema,
            ).events()

            datasets = get_datasets(events)
            for dataset_name, data in datasets.items():
                if dataset_name not in all_datasets:
                    all_datasets[dataset_name] = []
                all_datasets[dataset_name].append(data)

    with h5py.File(out_file, "w") as output:
        for dataset_name, all_data in all_datasets.items():
            concat_data = np.concatenate(all_data, axis=0)
            output.create_dataset(dataset_name, data=concat_data)


if __name__ == "__main__":
    main()
