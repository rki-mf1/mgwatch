import sourmash
from sourmash.sbtmh import SigLeaf
import os
import glob
import re

signatures_dir = "./test/signatures"
index_dir = "./test/index"
fasta_file = "./static/mgw_api/examples/GCF_000006945.2_ASM694v2_genomic.fna"

def main():
    # create min hashes
    #create_index()
    fasta_dict = read_fasta_file(fasta_file)
    kmers = [21,31,51]
    signature_list = calculate_signatures(fasta_dict, kmers)
    if not os.path.isdir("test"):
        os.mkdir("test")
    signature_file = os.path.join("test",f"test.sig.gz")
    with open(signature_file, "wb") as sig_file:
        sourmash.save_signatures(signature_list, sig_file, compression=1)

    # load signature
    run_sourmash_search(signature_file, kmers)

def create_index(kmers=[21,31,51]):
    #loaded_sig = list(sourmash.load_file_as_signatures(signatures_dir, ksize=21, select_moltype="DNA"))
    input_filenames = glob.glob(os.path.join(signatures_dir, "*.sig.gz"))
    #ksize = 21; tablesize = int(1e5); n_tables = 2
    #sbt = SBT(index=Nodegraph(ksize, tablesize, n_tables))
    tree21 = sourmash.sbtmh.create_sbt_index()
    tree31 = sourmash.sbtmh.create_sbt_index()
    tree51 = sourmash.sbtmh.create_sbt_index()
    for filename in input_filenames:
        print(filename)
        #ksize=21,
        sigs = sourmash.load_file_as_signatures(filename, select_moltype="DNA")
        for sig in sigs:
            if sig.minhash.scaled == 1000:
                leaf = SigLeaf(sig.md5sum(), sig)
                if sig.minhash.ksize == 21: tree21.add_node(leaf)
                if sig.minhash.ksize == 31: tree31.add_node(leaf)
                if sig.minhash.ksize == 51: tree51.add_node(leaf)
    tree21.save(os.path.join(index_dir, f"index_21.sbt.zip"))
    tree31.save(os.path.join(index_dir, f"index_31.sbt.zip"))
    tree51.save(os.path.join(index_dir, f"index_51.sbt.zip"))

def run_sourmash_search(signature_file, kmers):
    #tree = sourmash.load_file_as_index(index_dir)
    #sig.name, sig.minhash.ksize, sig.minhash.moltype, sig.minhash.num, sig.minhash.hashes, sig.minhash.scaled, sig.minhash.seed
    for k in kmers:
        SBT_file = os.path.join(index_dir, f"index_{k}.sbt.zip")
        tree = sourmash.load_file_as_index(SBT_file)
        sigs = list(sourmash.load_file_as_signatures(signature_file, ksize=k, select_moltype="DNA"))
        for sig in sigs:
            for similarity, found_sig, filename in tree.search(sig, threshold=0.01):
                print(f"query: {sig} | target: {found_sig} | similarity: {similarity} | cANI: {similarity ** (1./k)} | filename: {filename}")
        
        #for sig in sigs:
        #    for contained in tree.find("containment", sig):
        #        print(contained)
    # containment_ani(self, other, *, downsample=False, containment=None, confidence=0.95, estimate_ci=False)

def calculate_signatures(fasta_dict, kmers):
    signature_list = list()
    #mh = MinHash(n=0, ksize=K, is_protein=True, scaled=1)
    #sourmash_args.SaveSignaturesToFile
    for k in kmers:
        mh = sourmash.MinHash(n=0, ksize=k, scaled=1000)
        for name,seq in fasta_dict.items():
            mh.add_sequence(seq,force=True)
        sig = sourmash.SourmashSignature(mh, name=name)
        signature_list.append(sig)
    return signature_list

def read_fasta_file(fasta_file):
    fasta_dict, seq = dict(), ""
    with open(fasta_file, "r") as infa:
        for line in infa:
            line = line.strip()
            if re.match(r">", line):
                if seq: fasta_dict[name] = seq
                seq, name = "", line[1:12]
            else:
                seq += line
        fasta_dict[name] = seq
    return fasta_dict

if __name__ == "__main__":
    main()
