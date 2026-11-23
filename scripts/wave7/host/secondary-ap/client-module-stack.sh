#!/usr/bin/env bash
# Live matched PCIe stack trials; no changes to installed modules/initramfs.
set -Eeuo pipefail
[[ $# == 2 && ( $(id -un) == jan || $EUID == 0 ) ]] || exit 2
variant=$1
# One profile registry governs both the module guard and the two harnesses.
# A registered name still requires all five exact pins in the case below.
declare -A trace_profiles=(
    [quota]=quota
    [upstream-base]=none
    [upstream-prefix12]=none
    [upstream-prefix13]=admission
    [upstream-prefix14]=admission
    [upstream-prefix15]=admission
    [upstream-prefix17]=admission
    [upstream-prefix22]=none
    [upstream-prefix22-trace]=association
    [upstream-prefix22-band-trace]=association
    [upstream-prefix22-assoc-trace]=association
    [upstream-prefix22-assoc-rx-trace]=association-rx
    [upstream-prefix22-bss-trace]=association
    [upstream-prefix22-compact-mld-trace]=association
    [upstream-prefix22-membership-only-trace]=association-membership
    [upstream-prefix22-secondary-ps-trace]=association-beacon-power
    [upstream-prefix22-secondary-bcnft-trace]=association-beacon-power
    [upstream-prefix22-both-bcnft-trace]=association-beacon-power
    [upstream-prefix22-early-bcnft-trace]=association-beacon-power
    [upstream-prefix22-dev-band-trace]=association-dev-band
    [upstream-prefix22-secondary-first-trace]=association
    [upstream-prefix22-secondary-trace]=association
    [upstream-prefix22-primary-bss-band-trace]=association-rxtx
    [upstream-prefix22-authorize-links-trace]=association-rxtx
    [upstream-prefix22-authorize-delayed-links-trace]=association-rxtx
    [upstream-prefix22-authorize-single-link-trace]=association-rxtx
    [upstream-prefix22-authorize-primary-mld-trace]=association-rxtx
    [upstream-prefix22-postscan-txroute-trace]=association-rxtx
    [upstream-prefix22-force-secondary-data-trace]=association-rxtx
    [upstream-prefix22-secondary-txq-route-trace]=association-rxtx
    [upstream-prefix22-postscan-link-park-trace]=association-rxtx
    [upstream-prefix22-postscan-txroute-fw20261016]=association-rxtx
    [upstream-prefix22-postscan-roc-reacquire-trace]=association-rxtx
    [upstream-prefix22-authorize-bss-band-trace]=association-rxtx
    [upstream-prefix22-lifecycle-trace]=association-rxtx
    [upstream-prefix22-deferred-roc-trace]=association-rxtx
    [upstream-prefix22-secondary-rxtx-trace]=association-rxtx
    [upstream-prefix22-secondary-rx-trace]=association-rx
    [upstream-prefix22-assoc-eml-trace]=association
    [upstream-prefix22-primary-trace]=association
    [upstream-prefix23]=none
    [upstream-prefix23-trace]=association
    [upstream-prefix24]=none
    [upstream-mlo]=none
)
[[ $variant =~ ^[a-z0-9-]+$ && -n ${trace_profiles[$variant]:-} ]] || exit 2
variants=("${!trace_profiles[@]}")
action=$2
kver=7.4.0-rc1-2-cachyos-rc
bundle=/home/jan/firmware/wave7/kernel-tests/mt7925-single-channel-split/$variant
stage=/run/wave7-$variant-stack
timer=wave7-$variant-rollback.timer
firmware_variant=upstream-prefix22-postscan-txroute-fw20261016
firmware_source=/home/jan/firmware/wave7/mt7925-fw-trials/20261016-official
firmware_ram_sha=329c0e27f780550789e4eba47452731b1723f69f9e67f525d0e50bf3cd2978ac
firmware_patch_sha=67ff85f1a39d1a100a51abd8e2a26edd2f198d7052514b6b8981948b231e5016
modules=(mt76 mt76_connac_lib mt792x_lib mt7925_common mt7925e)
declare -A names=(
    [mt76]=mt76.ko
    [mt76_connac_lib]=mt76-connac-lib.ko
    [mt792x_lib]=mt792x-lib.ko
    [mt7925_common]=mt7925-common.ko
    [mt7925e]=mt7925e.ko
)
declare -A original_hash=(
    [mt76]=20c31e7c6ace30a613cd00fca9eb480809dc1d15db962d24a4d1ae44980a4e7d
    [mt76_connac_lib]=b06b4eb13743a352bae0ad9c52e59dee7ad68bd7fc405e34cb67279db00b8d16
    [mt792x_lib]=f5cc1fb4ad04d82002f817fdecae50dae39d8549b9eb6c50596142a3934ec120
    [mt7925_common]=546f70108a29c643d52cb35dfabc87dbaeb78847c57c657e0cf1b749d31920eb
    [mt7925e]=c5efe032e376f65d732a450b834ef4f7c31d679df54df6870ba5db0d040128b1
)
declare -A original_version=(
    [mt76]=D15DCBD555EF496E6A3289C
    [mt76_connac_lib]=28C58B8C1B27F42E194BA9E
    [mt792x_lib]=80A4F5B125A334C827CCD89
    [mt7925_common]=DB4C3E1671DC2EA009803A0
    [mt7925e]=C1250959DB6A9D56BD392B9
)
declare -A original_id=(
    [mt76]=93f5557bbb5672ab21596f86c86aaaa80d1b0984
    [mt76_connac_lib]=f1807a546ad9daedeeaba24e47318ec33a11bd17
    [mt792x_lib]=5645e041ffb7d3509557e24726492edd99c0dffc
    [mt7925_common]=a21f51d6bfde49340e3d05c4016d0395102caa69
    [mt7925e]=3322f96eed6473fb1aa3ee4100b9ef46092a0c21
)
case "$variant" in
quota)
declare -A candidate_hash=(
    [mt76]=05af6d762cf36e5109d9cff363ce764ae96b0703737d14022991ac64a0efbf60
    [mt76_connac_lib]=7bf307b342ec69f027a5fe9b3f6c92cc208f6fc3b09cf7e9a33d9f636c73d641
    [mt792x_lib]=77854efde3ab7d347d8c2022b23df915d58c9df005362b995d76c10c35891d08
    [mt7925_common]=4421685b5b07aac716cccf6f43113d324be55eb3427fc06e1c0c1a2e7f62f178
    [mt7925e]=ccc37f5d558e15b9f8912a0583d00c6bca344955aee53c34c8cfed30a5e48d9e
)
declare -A candidate_version=(
    [mt76]=24FD3CB8BD6EC4F8FF9B294
    [mt76_connac_lib]=9FEA98BF053467F9FB24EBD
    [mt792x_lib]=0F773A06E6A47065D1EAF20
    [mt7925_common]=E882C202FF34ABD6AFFEC2C
    [mt7925e]=71791C8DAD7FB01A84B3182
)
declare -A candidate_id=(
    [mt76]=5ce11fcdfddf16225e46e501f563d010951a8c03
    [mt76_connac_lib]=4010329d2479518ade6d7f0fd6aa620cd1ede997
    [mt792x_lib]=d55c01c189ab3fbd710539bef960cc317a1cfcfb
    [mt7925_common]=bdf64419ed55f334a370340944db19e6617c85bb
    [mt7925e]=c6db5ad30247861370b10ee8625cc511e8296f99
)
;;
upstream-base)
declare -A candidate_hash=(
    [mt76]=01d9c0b93eb61bf2259b005967f6fadd43718822c006df95613893c8e2a16fba
    [mt76_connac_lib]=f4d820123842237c338f8eafb93b8cf9d340ae38ad06dfe19c83edf8bc3bcb83
    [mt792x_lib]=cb5e396e3fa260206300ad5b51808aebadc70d0346ef011fcd88be10aba085c2
    [mt7925_common]=0f622c21070fd494304e10418eed9ca1d294ea06587f0097d9c1b1cee85a4215
    [mt7925e]=1fb8753ba3b989f722809ec0a7fee4a3afbbc6be724462cc831078466e27a0c8
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=8E0AFCBE21728971D1B12BD
    [mt792x_lib]=2FFD9248FB2CFA09C140033
    [mt7925_common]=2133CAC6AEA50398F57A5C6
    [mt7925e]=64076F735AF69D874943994
)
declare -A candidate_id=(
    [mt76]=72770fced7989400c0314046b03d00fb55fc8aa1
    [mt76_connac_lib]=748fbf5962be05a2bc223adc9f98899740be0451
    [mt792x_lib]=279286781fc7a2ef7f77974664c592eb23de9bb0
    [mt7925_common]=47874e23be3b7c5e71c2c38787df7da9bd054250
    [mt7925e]=94d57200722a856e04100ff9556a216f7a37ea24
)
;;
upstream-prefix12)
declare -A candidate_hash=(
    [mt76]=02763e1c5dcadd4b124be3532514c3dcb09d4716329e305a8c8e3fab7f700e49
    [mt76_connac_lib]=501bf569cd0e84c7b365b5629fd32248a842e8cce6f8e976f36aaf94ac677e92
    [mt792x_lib]=53a6518a24a1658732fd6ffe28eac39995f7e0b184da3e675ca11c491106619e
    [mt7925_common]=20f02f932eec876d5fe561c95987979263410102d3b3f07343ed9728d0c92e26
    [mt7925e]=df6b67be5b3a0ef12447ab3bfa43d2274aa39f9f9da670cf95719e1faa1bdb4b
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=1B9080F5C0CBA13F0F80B07
    [mt7925e]=A4B170554BA46F84100DE24
)
declare -A candidate_id=(
    [mt76]=531cda207c2ba2a03887062cae653e20ff1ae24e
    [mt76_connac_lib]=59f5ed570f7e6ff9ff70142c861c7193902a82e7
    [mt792x_lib]=66cf4ffdf8bbead0e21bbea22226a9db29994522
    [mt7925_common]=1c16532df29f7bc84d3ec0d936ae7a3ff446f061
    [mt7925e]=f7a07472d7e01e1d3adc7f40a870428e63ae6cfd
)
;;
upstream-prefix13)
declare -A candidate_hash=(
    [mt76]=03a7f7039ce2adea3e4c540a7c85507223c52c36b39f5d1e89b8d2ea55464d4b
    [mt76_connac_lib]=fb90e9e01776c7c8f257aeb95c5c0700d8a5c537063f0d6b9c640e2891f896f1
    [mt792x_lib]=92bd16ed486e8e1892d710fbdd019d1af9e2f5d1e5ba88ce9236fae3c0e51d02
    [mt7925_common]=48015e8423f11b8cc766b6013ee243f28d86fdfb734e2df101b34a0be785df0a
    [mt7925e]=57e1219464c07c13bd9ed966d8454b4a1b8bf95ec094190ffb9280dc0aa1a949
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=8E23371727982FF58347502
    [mt7925e]=75B6EB89C3859CEE39FA53C
)
declare -A candidate_id=(
    [mt76]=741c022f9d52d698bd9b1466f80fbf2e807180c3
    [mt76_connac_lib]=9a441d27ecdbc10ab8fd4a0114f790c49b5f3d94
    [mt792x_lib]=d86ba5e71c6df088c76da5f44f2b23749bdcf001
    [mt7925_common]=d6818992b24e867b49333120ae342f86e37fadfa
    [mt7925e]=1191d483c6fca55b0b4cf64e64ab589c2c5d639a
)
;;
upstream-prefix14)
declare -A candidate_hash=(
    [mt76]=d57b50c0cef23b9dbebcb31e5e1c54db8f571914b4410e7ecee2c2aab959bc53
    [mt76_connac_lib]=bbb3e19019eb1c843a04f9c2eb2bb82655df93e49a0b0e836f6f3b1dc9fec23b
    [mt792x_lib]=abbf05c844e29c496c9067572dbaf5d23f4ec216efcb2e10f12a2448a0bfd030
    [mt7925_common]=43f33a07039adb4eeaa0e8a60fe19ffafa290c276762f80cfe7e9625aed07672
    [mt7925e]=8c60dfdf2e35046ea77b260f9713bfaf4594725850b278b862c6f7ee56299543
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=8C873D9E4632AAEDC289499
    [mt7925e]=859E412691124815B463928
)
declare -A candidate_id=(
    [mt76]=f05d7fa6de77334dd72a08b270b509c3ea1bfc73
    [mt76_connac_lib]=7b916204ee5358147211f922ca7370fc959a02ed
    [mt792x_lib]=2be313e39de0b1cb607022e8ad3af4fbe40508e6
    [mt7925_common]=166ddba47d1a145864356095bc86aa1866679632
    [mt7925e]=82184f21b2920cdd2a46a5738bc98de3c6dc7615
)
;;
upstream-prefix15)
declare -A candidate_hash=(
    [mt76]=2e21654c77a1fb3c7eae008c44312681d03bc49b65ffe9adbcce2534ea56c334
    [mt76_connac_lib]=72085c91e9f5cbca8f6e257c38e268b216c20a0728878ffae0e82f9cde984f79
    [mt792x_lib]=87d5d384e9911dfe14a6165ff1e264935736f397d117446f609fe725d95ba62d
    [mt7925_common]=feae55e3f2829b24176f7bbe6018a8aefa52700367d815ef465db7c98955b7ce
    [mt7925e]=ebceb3c414bb28e22fd2874846db2c95276da3ebf51397907f2e5b064ce117d9
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=B9ADEA19B771CFE6230891F
    [mt7925e]=859E412691124815B463928
)
declare -A candidate_id=(
    [mt76]=ee889b83d45447c340bbf0b953e75e8b92c537bd
    [mt76_connac_lib]=f6fd3173b4d54a6243188edb38567e890058935d
    [mt792x_lib]=2ac804c59760fb0647bcd76083a6e00e0d84675f
    [mt7925_common]=4dce9cd598b5cb3f5b072cbba96cd8f4c5c64bc6
    [mt7925e]=8c8b3d93661271c34df1c2c94d331d90a272c0e1
)
;;
upstream-prefix17)
declare -A candidate_hash=(
    [mt76]=3fb7604606c013c73da23c8aa04d4547409d2ea261d2f91cdd9cc968fd6051b7
    [mt76_connac_lib]=797d56955696afd6c3065651c90f73edfe6754ef3d2ff13a8a2eab98e1b039b8
    [mt792x_lib]=8d41fce088a520b62d6f874502c82558c8a4dfe44ff9e901102c9dafb3f53410
    [mt7925_common]=48fd27d1afe6f3717730b37264cee0b05f5c3ff50185a4fc5d1b351e38eb42ca
    [mt7925e]=acbf2d5933d5c393ffd10047dd0db34c814a4846732bde8ef05bcd832982356d
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=2D2BA0973F604AA234A5E86
    [mt7925e]=859E412691124815B463928
)
declare -A candidate_id=(
    [mt76]=58c747fdebe80023813412e94f802a11c929354e
    [mt76_connac_lib]=90a8c587244c1443bce28de3a4472fe6f2d9d7ee
    [mt792x_lib]=1b8ca70aa90722ad2572e3c93d551081a9db0e34
    [mt7925_common]=5b211b270c392705dcd7d42277409d17c9e6ee37
    [mt7925e]=31449679a1b95b9ac01ee29ada9ca632d2c8e333
)
;;
upstream-prefix22)
declare -A candidate_hash=(
    [mt76]=2ef017e23a76f042885ef65a0f31d91dcc2ec7d5c72be742b389177a9fba202f
    [mt76_connac_lib]=65221babcfa4cbc2bfc327cfa43205cf691d901d536cdd74010795cf2f624cff
    [mt792x_lib]=5e3de7d06b86fcf440d6ee81cb89eb5343a39cffdae13998f75cb5720fe393e3
    [mt7925_common]=1a3c85b7c2e8f42bd59b27b32d1ca57fce8367b71b621c936fcf49beae03d8ef
    [mt7925e]=12970aba3c5cdad9855f2097a4b0d93b149a15aacbdcc0d5da277070789fe8ff
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=02F9A4E5F225A22FE7E645B
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=2be3dc354234f4ab8d8d445ac614b05e73aa5cf7
    [mt76_connac_lib]=54e94a8a76d2fbd607ba121e3272f7dc4c03d2a1
    [mt792x_lib]=34fa10d446459c8ea3b625370a601a482b22393a
    [mt7925_common]=93e3823cf794c4e2a2e3b74e76be62bde20f5eb8
    [mt7925e]=fa2ef1e5e775fc6ff70fb4e634d8075ba84d8991
)
;;
upstream-prefix22-trace)
declare -A candidate_hash=(
    [mt76]=a65561f7b448b76e4169386aeae0fdef3d858798425c7f71e2986e565fa1e7bc
    [mt76_connac_lib]=f0172105abe17e8cc838a4cad7463fd90c0c2401a70a976a4314188c11425b99
    [mt792x_lib]=3d1157e1dcb5953499e3d0984aeefe267d3c41e664a5ac4d317b3e0740955b9c
    [mt7925_common]=cb7a644f9985cf960d88c15ce2d3582f20a1c58774feb5091ff2d10ac2a1a91a
    [mt7925e]=006f13bf6508b2f66170c2343b6c47c993ab23d52e9f2c5edc383ee151a5b4da
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=2DD72F664C92D6C8366171F
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=5ba75d7b1ebd3fdf2884d7f1d5998d8f38913399
    [mt76_connac_lib]=fc81c25ea651509331ca819a52224918294dd732
    [mt792x_lib]=38ad382f8bda35cd16e89688fafb061eb31b7613
    [mt7925_common]=1bf4dce0e0e4287a45a4aa183c12cceb4d788ef6
    [mt7925e]=73c3e9b4cc66a92df36c6db35adf3da3d4442b9e
)
;;
upstream-prefix22-band-trace)
declare -A candidate_hash=(
    [mt76]=36db006732715b7dbcd1ea70e5358c2d9fb8b3f446ff805b12813ca4c77b72bf
    [mt76_connac_lib]=0780de0fbebadd527b5876b3946a3fe3f071973bbc76055570fc7c9bf5bb8d7b
    [mt792x_lib]=96890be3db990582f3fd8e6e6eafe381be6d1263378435c772dadc8f494f9253
    [mt7925_common]=b5d10759dca3dd40c3f07f1e88466edfa59923b9916d050dcb0ce46582b264bd
    [mt7925e]=62b9fff6b906fcb93fbbb8ec685c222af476f371dfdbbff07bf7b55e6559db5e
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=5DF4D704FA256852750A988
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=3d1041cb53bb229395a49f9b093cb4e06da6a8f9
    [mt76_connac_lib]=c8b07033739bc828f627a20035416c28009204d2
    [mt792x_lib]=da27c52af71540034576039ec05db2bf6e47e512
    [mt7925_common]=5ac1719ace3d3494b7df43414d9505e958a84e65
    [mt7925e]=b14edb371011f9a7ac2f70c6c41f35ec7548d4b1
)
;;
upstream-prefix22-assoc-trace)
declare -A candidate_hash=(
    [mt76]=0925193a2f9a94630c2dea393a6a8fa67bad17ed976b4dc664fda073bc63c021
    [mt76_connac_lib]=11d827fc08fa52804987a9e8e6e7b55d9d8ef92364665e0a3257dd54e8e8e81c
    [mt792x_lib]=a8524594c22fc1c2dcca37a91446a3b5ce1803f04b5f980e96de04453999e433
    [mt7925_common]=7f80c385bd530e478b8574d659a2fb1d15a81250ce1dafcd043efc3770daa207
    [mt7925e]=604791894588ed377f5269ea1c901ec974015f6a4602f86a69eace699f5966f7
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=934FEFC57A5E709A0ED49D9
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=0cfca9f3d91e1007fd1f972561f418cdf6d47d0d
    [mt76_connac_lib]=6752648599a66d8a4922ef92596e34d17a2ea662
    [mt792x_lib]=8d49fcb9319a37da5bc44b005ca3464cbd66f0ae
    [mt7925_common]=6ead0b9f354496770ff6517b95aebf6f5e572953
    [mt7925e]=815ed3c9c070eb49233926e3cf7765a7caef7498
)
;;
upstream-prefix22-assoc-rx-trace)
declare -A candidate_hash=(
    [mt76]=3e3d43f2bf3867490f2fda6e637d38ae7d494afa8fed1c42646203e82d920e5f
    [mt76_connac_lib]=eb3232fb5ce7a553a6221d241e7d2ecba7d280c1a033ab19d7fdf6168f5ea17f
    [mt792x_lib]=6e5d33676d4dc1801f7a19cb55a59cf686acd6068a1d688e4a53c4ded4f1d588
    [mt7925_common]=b4890a2692617dec0244bf4d228833debe92faa799949576e679b59dcd93dd81
    [mt7925e]=999b60fa5f9d1284e5d946951cd44bf920b969592ffa2b48dc2331776b8792c0
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=7994800FE6A3B236CFDD14C
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=e8b90edfa52d5d2130bd69d4f770e4f7b8c579cb
    [mt76_connac_lib]=a746f62c6a52ee606083622d00665a2405aba653
    [mt792x_lib]=42400ac1ac088a43941a115f2b5125a29421ba90
    [mt7925_common]=10cb7a27c0b2f19be296fa59bcc2aa49a3517006
    [mt7925e]=ea28967cf52c949d793fdcf61f7ba7fab64b6c75
)
;;
upstream-prefix22-primary-bss-band-trace)
declare -A candidate_hash=(
    [mt76]=6d254d820f1c8a54b73cee36c27fb297fa5a30d84b5f9ff2b675f53ec4697003
    [mt76_connac_lib]=b51a2de9df0f617f071970ce9420b8f8a110a1c04acebc2ee3e0fe3c0ef37aea
    [mt792x_lib]=da8f6992b2863f62eeb759a528ae66c69864f9b45970ebb52d369736eac564ed
    [mt7925_common]=2bf6e8a7efb55ae6f1217e7e917d8232ee74581a9e149a1f87efa72962c00eab
    [mt7925e]=d17614995e91f48e7e45e376cd8bd9813c89d06a8ed6c3edc7b74ca45bbf2f49
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=FD8E9521D266830DAE7B7AC
    [mt7925e]=699B898B8A788927D144FAB
)
declare -A candidate_id=(
    [mt76]=da054466dd9171870abeefac28fb6b59530d6f8d
    [mt76_connac_lib]=588307a1b961cec1083de8610f4a3872e4186f57
    [mt792x_lib]=f1aee6ccc9fcafee5a2171f8b5af9a3cceea8999
    [mt7925_common]=01b3a91d74452bdab5ea18b685eb1715a49b8c55
    [mt7925e]=419b8e405780f1c257a150e88a5922ba26750b31
)
;;
upstream-prefix22-authorize-links-trace)
declare -A candidate_hash=(
    [mt76]=8a9eefae5349c3bcb9d3faf093482020004721b6d390ee2a1b02d5658966e4d5
    [mt76_connac_lib]=0e87150c759fcfcc1fa5f12f433d987147376c7989e2bccb1e23eb1f4d183e3b
    [mt792x_lib]=c188c9a11fbc5803cf8a68970b0007798911db895d63ce1efe362ae9eb39a991
    [mt7925_common]=1e4d51b44cbc10cc5b1a0f3ce73dae42a5b5b8458c82e12ef45a19f521678b08
    [mt7925e]=171a1e10359b52ebee5d95155e02dcd76224af86051fec990879ceee252c54f8
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=6E4ED960E1E397EAF605336
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=9041aec59e63b26a98684bf68ba4be3adb30d022
    [mt76_connac_lib]=25647e734bb616910ab074090094e80d13795f4a
    [mt792x_lib]=938cb52e1f9d19ef5b80eb243e1d49218df1a346
    [mt7925_common]=877973115f005ca1e603a9960f773541b338eb6e
    [mt7925e]=ea554df802ef442d21c135ba6f31b19f84ed6b72
)
;;
upstream-prefix22-authorize-delayed-links-trace)
declare -A candidate_hash=(
    [mt76]=ffb6b169685e64b9c1cec8de68c630e0ab414655e392b66f6f97db9fa4294bef
    [mt76_connac_lib]=125afc654fa8ca17e51228751d67b711f968d3c02de61ed6cb921039f950b94d
    [mt792x_lib]=4f3f9d750bd8f65407dea10710de22b797ddc1b6c353a7d0f91cc3f982c85f05
    [mt7925_common]=48dbd2d8d88dc276bad4bf821b052aa0a2bb229bcce0b00eb7419ffffc8e2e21
    [mt7925e]=e43919abca6de0f01aadea7dcf8d14efbbf451bb67a537ce5fc41543120268a4
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=1021DF811B8BAB2F6A2CD84
    [mt7925e]=9987F1D81F5F315E616BA00
)
declare -A candidate_id=(
    [mt76]=a97dd5defc14c2491db74c4c5db6ddd36b47ced2
    [mt76_connac_lib]=5081d427298d91cdab11163579a45bd42e9ad179
    [mt792x_lib]=70338cba2c29c6b94065670e34b312be266b7947
    [mt7925_common]=b5fa47d6f5fa20c605fc17e20012c64be23e400a
    [mt7925e]=05b4c80fa7bf779d5ee6ac1d91c0a4605ef65e92
)
;;
upstream-prefix22-authorize-single-link-trace)
declare -A candidate_hash=(
    [mt76]=9755bbdb8bcb58f86f23893b01d89033384589480913cfb88898493dab271430
    [mt76_connac_lib]=e01ba97984128b386e8e213d3a5f90be0d9be1cc06e1f861b126d9d6d3750807
    [mt792x_lib]=66601d8ffa7ace2deed154a4f19bb23e7443c285e53bd83d2feb5c212d69c153
    [mt7925_common]=db0111cc02435580ff85dd771cc66a4550966b83ca4237701db5e8e58ccec57c
    [mt7925e]=bb02cce89c807b57b5fca607da64afb6818bdc976a530498c54a66ede68814c3
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=69455DEAE47FE111C34ADB0
    [mt7925e]=9987F1D81F5F315E616BA00
)
declare -A candidate_id=(
    [mt76]=4c299910de6d2cb8712a617385f05506aab814e6
    [mt76_connac_lib]=3756b43dbaa4ca6523f224617bc1044415515e56
    [mt792x_lib]=7269e2a6738450d36cd1cbf3d6c21e39401c973b
    [mt7925_common]=188bd44c51a8e593aa8d39d05a94f28b4c7d289e
    [mt7925e]=21c5aed41e79bab96f5f197b51ea2ec2cd3fd5f9
)
;;
upstream-prefix22-postscan-roc-reacquire-trace)
declare -A candidate_hash=(
    [mt76]=9c28864c41a7d447a84ef1b6a8440b25a7e2524d1ef5a9911e26d738e9a2d618
    [mt76_connac_lib]=e46107b135c18b83ba8b38d54f6150dd707fc17166865ba56ff0c1afb0d688b4
    [mt792x_lib]=8eb2454a730a2a2cce10d957842902f132ce4ab0e6ea8b687dcf736bf8ae6751
    [mt7925_common]=68b480ea163e7112a7dbc0e23475ff003ecbc92a2ddd790cdd31cc962934ccc4
    [mt7925e]=77554cd858d0cf22a6eb3b735f7323a0c5aec5daf513404e2894826f654446bf
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=C60C52C974CD57E78C740DC
    [mt7925e]=9987F1D81F5F315E616BA00
)
declare -A candidate_id=(
    [mt76]=b18f2a338702b6ac10cebfeafd87c3665e52702a
    [mt76_connac_lib]=a1c1b257f53e3686267f0567e926e2dbf2adac4c
    [mt792x_lib]=5f77135df1323baa5f4943522fb16133c4954195
    [mt7925_common]=853a318dcce80e549469711777c59048199d61c1
    [mt7925e]=7841c56b0c951529abfc3c1e05b004dde0994252
)
;;
upstream-prefix22-postscan-link-park-trace)
declare -A candidate_hash=(
    [mt76]=4cb8c870d044b118fb09fd77e7574cec60ace59ec74a410567c7a7b0d6f51258
    [mt76_connac_lib]=0df0d5774d579214424eb7f4f59900ccaae8662a45825058ea2d21e77a55dc6c
    [mt792x_lib]=51586527930cc3e280a010f93a0424a7e3c6830474893cf95536242bd0acf661
    [mt7925_common]=b60fed18d47f839cfc875e0be0a6d91249b3816b4d1bca4d45613850916ba080
    [mt7925e]=b4b9a7bd2ac0cf179911a2f07c967441c5dd38e39f4c8ec94d940dff5a7f003e
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=4864AA5F3E21902FBE15BD1
    [mt7925e]=9987F1D81F5F315E616BA00
)
declare -A candidate_id=(
    [mt76]=24c889c770221df4e350bc210e552c45a1c7083e
    [mt76_connac_lib]=8175e80edd333de073d717c107cad4c4fc9622a6
    [mt792x_lib]=ad13b707ac28a2c4423b74813a302563a7b4d43f
    [mt7925_common]=d7fa623fbac6c9ceb7ac89861166bb943044a6e7
    [mt7925e]=31ccdbb497508e416aa2906121a7602a597ac3d5
)
;;
upstream-prefix22-force-secondary-data-trace)
declare -A candidate_hash=(
    [mt76]=a2971c479d6f6236856d4fe034140d044477f563f2c4b7c578b3f5cec422d162
    [mt76_connac_lib]=ff4b666e1e50ccaf00e4586c5aa0799065e406c891765dddea49d5ce30da4b2a
    [mt792x_lib]=8a9da324acf19be85dd562e6a4f4cfdcf299ad0cdb1e5b5ed6680ea30408cfff
    [mt7925_common]=fd28b19169ea13f2767adbb8fbe87bedc3c638c87b13e508a68d818c521695d4
    [mt7925e]=82e2b1b7d9c9c0eb61326167e14a61abcd1b2404ec131337c9e6942731d69d5c
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=B4C9EE6571F53C3E171E2B9
    [mt792x_lib]=6AA3CA4AAAACB3E40A80B03
    [mt7925_common]=DC2F15E99A5F66BFBF4F3AC
    [mt7925e]=9987F1D81F5F315E616BA00
)
declare -A candidate_id=(
    [mt76]=5a06763c970e487bdebef9043a76d5bc5227c28f
    [mt76_connac_lib]=02b20987bca5e48ab730302da97f991e486235c0
    [mt792x_lib]=a2cb2f70639e884af56e678306bb02425466f2d4
    [mt7925_common]=3a256c3884bf6c31e69a10b2b59b821cd7f53d01
    [mt7925e]=14a3373cc453d55a0ed892e85b33371c0f4d8202
)
;;
upstream-prefix22-secondary-txq-route-trace)
declare -A candidate_hash=(
    [mt76]=1b0746f3344d67b34eaaf204ca312272083bd3866be94526c667001b6fa67d03
    [mt76_connac_lib]=6e3ccc173345a4a2119a6ce2583a468254cc8142f755d8c9618214dd64ec536d
    [mt792x_lib]=07f6f1597dc3f6985a75e1ff947cadc17a4f44a27792483b8dd99c863d071cce
    [mt7925_common]=0990d4e9141c6d524bb45c6dc3cce1219c7305d64ee598eb31424757e0982689
    [mt7925e]=430e7894394fd6690832201a538e39b7a89d912af2232f97561b6e73730afa5b
)
declare -A candidate_version=(
    [mt76]=457A82283B28F81EFDD8731
    [mt76_connac_lib]=B4C9EE6571F53C3E171E2B9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=21C5786771FBC6BF147BADC
    [mt7925e]=8E8CA598D13720CA3AAA078
)
declare -A candidate_id=(
    [mt76]=66b1e1352ab532478f8bd4aad31078094603f883
    [mt76_connac_lib]=4579cebd1c669980ac9f27a2ba641bab86d4612c
    [mt792x_lib]=f97965ffca32226b4aa9b82f73ee0df225ab0933
    [mt7925_common]=2ea64e49c20e685fac4bc8ba833f424443e0de57
    [mt7925e]=ac8e5b6c50d0865378299ac8e259496549834f9e
)
;;
upstream-prefix22-postscan-txroute-trace|upstream-prefix22-postscan-txroute-fw20261016)
declare -A candidate_hash=(
    [mt76]=9625bc9cc20c811c201d5d13967117c723d77706f802062ae7d8675ff1b0b772
    [mt76_connac_lib]=5dea1de50438e65cd09d7f98f3ac9a53aaa6dcfdd45451cc54436d570c724b85
    [mt792x_lib]=413cfaed8e04fa02e573fd4493840d15e57895d9f648776e57fa01ea3902fc2a
    [mt7925_common]=e2656e9e24f72385acf06de1340c10ef8832f51b597d9c1a230b20477b4bbe3e
    [mt7925e]=43cff2d6a39b65f96db18649e632e34b509e34a3fab574902835a3bc1bfbf690
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=183CB5620804932CB5B225C
    [mt7925e]=9987F1D81F5F315E616BA00
)
declare -A candidate_id=(
    [mt76]=7cf16b919f45d9366d365d2ac114b1a94d503d1f
    [mt76_connac_lib]=18813ebf17931ac6b848a7e36c130b9fb6081722
    [mt792x_lib]=716a252dcd7fa8a596f5078f932c73a1416e6baa
    [mt7925_common]=270a04ea67f5e6d5b765f190c930a9595ae17671
    [mt7925e]=66bde980167f17918816a03621f8427c3dcf8179
)
;;
upstream-prefix22-authorize-primary-mld-trace)
declare -A candidate_hash=(
    [mt76]=f93001407c73e39ca5ed0ef01b346f3b0f4c68f4d9a1e3c41056c191a9d94ef7
    [mt76_connac_lib]=c1bdad71232521126170ef192c30cd4f6f9617c3ae173ab1d1847e4056f42f42
    [mt792x_lib]=b451ef4fd70be48d96bb3d54ab0770106127faf6324ba3b48ce2245ea98cfad9
    [mt7925_common]=8745e054515790751d1d6bb7ec5cc5610dc506e26b2815fee62a6c2bc4b9ce3e
    [mt7925e]=b07ddee833cd081d416fbcf0f749ee80c1f0551da27df9f359b6a8f66e70cce7
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=4BB698AC9B78F731443B4A3
    [mt7925e]=9987F1D81F5F315E616BA00
)
declare -A candidate_id=(
    [mt76]=b34849101dc7c625b59734ddeacf09fdd9139141
    [mt76_connac_lib]=dcc1d80719166af854521d8b6654afdda200725b
    [mt792x_lib]=31c873489acfffcbbaf5291acfa94fc50efa24fe
    [mt7925_common]=2340b11487e3c4ba53116f73c6c3a4d3de65caed
    [mt7925e]=6471b6996bcc18546f02d468090cd0d6ee19407f
)
;;
upstream-prefix22-authorize-bss-band-trace)
declare -A candidate_hash=(
    [mt76]=7e66c75824d1c4d74ecc01623acb85173fd864a3e130fa023a1020e889ae9457
    [mt76_connac_lib]=b66e9b4c298772b56353be6329b165ba50f847cce6b281646ede42a1f5fd8762
    [mt792x_lib]=9a4b50728d6f7f9ce73ca5b9a842eec6acbbc46e102accd2cb2408bfe5e86930
    [mt7925_common]=d273b1957390c74f19c3d97ce8a063ff15d53d751d6acf8b45b460ed68be6082
    [mt7925e]=30f4427eade78fa4d73980ca920a90c3fc4fe5ae7d601b0cef4bcfb61345f1dd
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=31FDE2532BF6CB458DB337D
    [mt7925e]=699B898B8A788927D144FAB
)
declare -A candidate_id=(
    [mt76]=7c0e167459b6ba3e0f7d021737ae570f46c38a16
    [mt76_connac_lib]=5d35da385e24320139a4fc50a70738a6383ab4d1
    [mt792x_lib]=355c9ae932b75de3a9b5d3df475c635c4f553b30
    [mt7925_common]=40ae7679cf12ffb123f1848c10c0aadcda5016d3
    [mt7925e]=22037b9ce1770bb7435d6f4f3fd7b09661e047ed
)
;;
upstream-prefix22-lifecycle-trace)
declare -A candidate_hash=(
    [mt76]=2910a1dd14c01b95dfdff6d587ab0926b6d027efb70d76bc9b3b0c947e6225b6
    [mt76_connac_lib]=941647f3f94d9cb8ef73b517c5d4b0198f3dd05c9082f4c5d37c761dc891481e
    [mt792x_lib]=843d4b81c310c96322f54ec938af2df56da9f65e2970a6e4ddf24254d9796ff6
    [mt7925_common]=758ae44223254e23c0bd0a9e7d9be1458cc05d672441217e838e5cf4b1401d11
    [mt7925e]=52c89592d3a063ea198c8e3204dbe7d1f320272e3d82f3398ccf8591d48b51ed
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=749A4015F0F3E1F3C96A6C9
    [mt792x_lib]=A681310C17DD1275877F354
    [mt7925_common]=18608C5B429F0374D3513BA
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=eef3660b276e35ad9801499281c031021f932e18
    [mt76_connac_lib]=ea4f83cd40661a7d7225195e8e19294e46fac8c6
    [mt792x_lib]=94252d2632d354cd8a559edf510a2bcea2242625
    [mt7925_common]=ebe3b2ffd06b87aef2deb724fbc2f072bee9a3f7
    [mt7925e]=c14e215c22e3d47363599ec5c69350986fac05a3
)
;;
upstream-prefix22-deferred-roc-trace)
declare -A candidate_hash=(
    [mt76]=54a43e2f99d3e09d8f106137efb7d95fa9236d49df167d19be804782948491ae
    [mt76_connac_lib]=95c09769bd5f1cebc511a44387dc2140ca0ea7368aedefcc57de765475226ede
    [mt792x_lib]=0d24da291deb538f67b02d80cf6fad99bd4b5b60085d5dff67ec5ea00a94a407
    [mt7925_common]=9bb2694db226ec340c5c1b53393a9b41f856d7ca2a5a94af607bc312377ad9fe
    [mt7925e]=5d98813e806d89282fcde6f85352a365eb837a6fdf76830be3ec78ff2aef40d0
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=8C1D04172B632276A37B55B
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=d7d13044243928878afcc132ce5fa01d7b3112bb
    [mt76_connac_lib]=6d941ed32dfa504605912b354435993e2f30928e
    [mt792x_lib]=ec73c91fa5e6cf2b913dbf00648d5a78c7e38dea
    [mt7925_common]=8e58915f282aea1c6e37ed8e7c7afcbdc6ff2024
    [mt7925e]=5aa407c1178851676055af81b1a96b54af3ebe2b
)
;;
upstream-prefix22-secondary-rxtx-trace)
declare -A candidate_hash=(
    [mt76]=1c6dc56e19241949e99f4809ee4d7f2372a4ee20127d269d946c05fd838850e3
    [mt76_connac_lib]=ca73278669f8d51cabf2b38062cfdd91f3718fcf6a8bb04273c1bfc76ebaf529
    [mt792x_lib]=f04c5499d7c9c7bc08a4f1935a49b13304c21ca9f25bc99e3fbbc1d40086b690
    [mt7925_common]=8055d30954755ed01e6f44f9553cf1975cce36bc463a4bcc6df8f5af893928ac
    [mt7925e]=c7d679e39226c7a3ba154a24b37eb36c2343f5e2b5b6871d166bcd144a095fa7
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=810442B0F5F37FA38903277
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=59591314ee02dffcff9fa54dc14ea424ef30a421
    [mt76_connac_lib]=77096c25698654a7bbd2a6954e19c43ea4dad7f1
    [mt792x_lib]=6bc3a36818dd2184ddf3a4f05df5900999b39e0a
    [mt7925_common]=25c73a0193c06be7b2beb8f684c266905c1d6be9
    [mt7925e]=2b175b12cd92e1c4d78dbdb347f6c66ef786b394
)
;;
upstream-prefix22-secondary-rx-trace)
declare -A candidate_hash=(
    [mt76]=361347a1b7fb9c17c95611ca4d3b2f0a0c3d1b9947dc0ee5901154e4ed716724
    [mt76_connac_lib]=a6e697ca6140d23e4a135c86fa562e6caeba7de4d0c76414faaaaf36c762c20c
    [mt792x_lib]=f8c7ae61fa61183c910369ab513b8db57fd41b392aee26c98b53715413421619
    [mt7925_common]=86a666ef1588989db6715743e8f78ea9d8f1ee679fd282bcfe4d4c876b697f91
    [mt7925e]=828dab8bd74b8860b284a839cbf7302d65ed2f3f2e0710e3cfb03a61f121c5ed
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=9AF7782FF291D3BDAA0FFE0
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=21d183cbe64650453fba19bb2e4041511aed7363
    [mt76_connac_lib]=f3f68d5693f4f354230df787999587775d9179fe
    [mt792x_lib]=f30f30f2893f09129d9102aba6fc6bd6383a22a6
    [mt7925_common]=6c833b5f812616729b59e4be215e6c1077ee270a
    [mt7925e]=fba443136454fab44c6dde4bc63c783415b6ff86
)
;;
upstream-prefix22-compact-mld-trace)
declare -A candidate_hash=(
    [mt76]=c2d374f1aaf1a9a8a387fa91f63ac0843c43d9955c5979c49af755a62d01c46d
    [mt76_connac_lib]=8fa593057bc9fed84ddd53ae0a5048e210c4680451bd70b81182830f76b0e83a
    [mt792x_lib]=9aef247fa774f6e2af8719143d398a814a5a10429ee733f82e91c04516179523
    [mt7925_common]=ce8ad40a2c4b714ffe7f5d03446cf6c95d61a1eb295b060f46d697c37797622d
    [mt7925e]=a1fcbc4d46a65be82a82dbca6544534c29eb19df170980ea5ef8f542ad7e1884
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=DF5D529299BD7FB51579319
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=5a336a32e509113512294531916b26e6e418fafb
    [mt76_connac_lib]=32a02196b0f60ba88812b239ad6691aaca7e121a
    [mt792x_lib]=05b75b2def77b8ea40e8921a782af846ddfd3444
    [mt7925_common]=9b36588b181d72bfa6310e5c65d3d1a4c16f5110
    [mt7925e]=a698009559b5574380eff6d901c80e984229a113
)
;;
upstream-prefix22-dev-band-trace)
declare -A candidate_hash=(
    [mt76]=c859b5ab8ee2cc5290a22c0fc2e45b0a5f27961915ff06c049d952033a1b0d88
    [mt76_connac_lib]=ad448cc4f6a98d5e6d88a2d2595e04c32445745a22954e77cc93d5bd6aebbe15
    [mt792x_lib]=9e7b6aaf2ec83171316b8692598084318e0cc4befc9ce174c45125f7b9af58c5
    [mt7925_common]=0c160c4c0cdbef8d55a76a124c561aa131fec4308df3d1ed8faa75c0bdf8ad93
    [mt7925e]=c805dc42a2c1a4b730cf283aaf61287ba7f5edd5b98c3b1a07707445ea9482f6
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=0117BF119B657EAF6853A8A
    [mt7925e]=416B52992616E7964206D72
)
declare -A candidate_id=(
    [mt76]=f5798960fbe79bc18c8aa4aded5d4c901910a9f3
    [mt76_connac_lib]=cd46ccdb5841182ab4c7492deae55fc9ae510663
    [mt792x_lib]=657047330665e7afafd4a9cb4de3999267b2b406
    [mt7925_common]=69efd3cbb473cb1dbc59f02b2b9d9ebf49553eac
    [mt7925e]=4a73f6c2039cf25880619a4028e45de6dea09c4c
)
;;
upstream-prefix22-early-bcnft-trace)
declare -A candidate_hash=(
    [mt76]=79051dca504729a022ce53b73c55948114c0d1e42a0f1cc130e5cc3a5fc09bf0
    [mt76_connac_lib]=37b653b96bb8cdf286b335dc95063044955b26ff47b884865b0030d070752b6f
    [mt792x_lib]=52e9159369fded8690f42bbae43ca64ebfce209b1e2374984ddd2d5ec0db712f
    [mt7925_common]=e8df017957cf76d97aa2449095969b29e7041f981a8ff0f9d51d366864736848
    [mt7925e]=f422ab8d5975741a80cbe54838aa494c76258b434f2c33d2d89ac141e7a799ac
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=284F4FF98861075AF878CAF
    [mt7925e]=416B52992616E7964206D72
)
declare -A candidate_id=(
    [mt76]=5ba591b738185828796e7e79d6a70a331a902371
    [mt76_connac_lib]=a9eb97b4f24d62abd0bb25369939b1149a593ea4
    [mt792x_lib]=f43f2d62f939846f9bccabcaaa772902fca37b59
    [mt7925_common]=dd7fbdc3657f842f90856e0b7d670a24f44162ae
    [mt7925e]=63d4b084389223716ee8b20f819c7c7e8ca697db
)
;;
upstream-prefix22-both-bcnft-trace)
declare -A candidate_hash=(
    [mt76]=49ca832819194c8fb6f2453a49f0cdfced0f134586441e577987a7258a08cc8f
    [mt76_connac_lib]=88a646c228675d7a5685b90c71b724ca0fc1d3901090cf5a7cc65e32508c1df8
    [mt792x_lib]=28fbe90a845c011bbfe12a6990e20f399a56948093727520ef6c07de1d2ce69f
    [mt7925_common]=32499f662b8e6d905dc7269c17181678688bbd8311986a646b3ebd1343ad2d68
    [mt7925e]=4d05f9e3996e958e9750a77a972af276aa3adecdfaef0b52e30d2358d2ff2ed9
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=33868CFB754C4904905FF71
    [mt7925e]=416B52992616E7964206D72
)
declare -A candidate_id=(
    [mt76]=9a06cbf5f838e3c9bfe59a39b83577b56aae8b76
    [mt76_connac_lib]=8443d229b39de48929d231a62f358b3d38d3d060
    [mt792x_lib]=0b627bcc8291d39d4a8794309d27832f813245f5
    [mt7925_common]=8127f9c84d5375f48f515d3ff4f02d3f8f4d065b
    [mt7925e]=67a3a39adca5ae1c0d9dbb7034931b21ae1d319a
)
;;
upstream-prefix22-secondary-bcnft-trace)
declare -A candidate_hash=(
    [mt76]=acd2aaeb7e773f72b1a0bed9e6878eeeefe89534d2af86738e03a3d57582c73f
    [mt76_connac_lib]=a2b925661c9c58670e6f568cae457c7363fa28cec4a4ad31a8d5d84d14da4871
    [mt792x_lib]=3f40fe0fff00c5830ee09e0c8858971b0dc3e62af89e0811ba0be572be4321af
    [mt7925_common]=7691a7f843eb926e5ab1e3f7683777626725f3d731e820c6ed9c16e0d0351486
    [mt7925e]=c1b040274d8ad1037a95a117aae3d109ab0ea83bcaa20ba3d0276664c501fa9a
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=49312DDDD39FDEEF37DA8FA
    [mt7925e]=416B52992616E7964206D72
)
declare -A candidate_id=(
    [mt76]=833d7e45d5ccf35eb0bf32b8311a0177b7556fbb
    [mt76_connac_lib]=1165f009de3a5dea0de778faca9260350397f4bf
    [mt792x_lib]=bc1636943a1cb871a8ce674aed9ca789c04be5fa
    [mt7925_common]=0a96fbe1508772eb7d3d3cc15b0146e1963e3941
    [mt7925e]=f8b71a3a40db720a640214d91cd36123b59eb39e
)
;;
upstream-prefix22-secondary-ps-trace)
declare -A candidate_hash=(
    [mt76]=ba48ffcbc2606dbd41c53fd609aeed49c29586bf15f48ac462084f8e710434c9
    [mt76_connac_lib]=9bd72450de9b1638cb660609003dc2c67dd1163428628a3e29e0e3c2a9389091
    [mt792x_lib]=1f11897588a73928c7b0a7263dc181ddf07d91f9ec2222c5f3f0fccd22c76941
    [mt7925_common]=1e5a6731d6e74fd9038f6a0a6deb8775179196d0c6ba647991a06acd918928db
    [mt7925e]=0b2c5634b6fad860a97f62af122d0f8ff55e1d6f34c909924fe5a4698fa83cb7
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=AB44E681E6F8F278A97A577
    [mt7925e]=416B52992616E7964206D72
)
declare -A candidate_id=(
    [mt76]=0d75d3eb3f69b4d47fe6e7bf88fe20eb063753ed
    [mt76_connac_lib]=6cfc9b7b8ad0c907bfd01c64fe01448e652eca33
    [mt792x_lib]=a785e9effc5ab9d770a4cde0b8a973bab8be8860
    [mt7925_common]=33468ed6b1628f3117b4a108645ab6a9e761ff8d
    [mt7925e]=869737849ccfdf3c1d500aeacf2081145b0026ea
)
;;
upstream-prefix22-membership-only-trace)
declare -A candidate_hash=(
    [mt76]=be17480eef998c8cea5d4eda14d645faee478262d76242804b15e0c81df61d2e
    [mt76_connac_lib]=9945d26d13665a8b79d5977bd0371fe057635b6dd325b482ea4900d7aba57441
    [mt792x_lib]=dbef79e2bb7a262991690a08cdc6112aab4f65028a030f96480ee476220cf391
    [mt7925_common]=cac7ff772c3d31278c089a6131379aa98ba578f41269f37b916189f7128b14a4
    [mt7925e]=0243ab4b4b822b8bb7436b0bae995ec6ae5030041387725acd10a8ebb684cc36
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=5929279DAC1C2C0185C984E
    [mt7925e]=416B52992616E7964206D72
)
declare -A candidate_id=(
    [mt76]=a0886500d20b3e066ad3d37c08276a1220110b07
    [mt76_connac_lib]=8224916a477c821e8e168241f74dcfc0f7727b2f
    [mt792x_lib]=8d95f8b265984f086de579b5aa5943d1803b3a2e
    [mt7925_common]=f5bb92d53b55556bbb903ed42e1a0cd7c08a392b
    [mt7925e]=6f5c3a21c5153d8827adea866291232a119bf1ec
)
;;
upstream-prefix22-secondary-first-trace)
declare -A candidate_hash=(
    [mt76]=badf6887ea7bbc8ce03ff3485bbacacf22cd5266e8012abb943d353f96ec3c6b
    [mt76_connac_lib]=eeaddcefc72e5c28b4734be0e1289ef11d3abba37141151d521eb23f8b7bb94c
    [mt792x_lib]=28f8d32f2f0f2eedc979e9c207cda12b42309de69e2302eb3bb28e71cf6f9645
    [mt7925_common]=43e26226c4e33bc0679939a7336c43431b4148407750e86e687d2329e7842cf5
    [mt7925e]=14fc2a0c9079ae8433f4b6afe551bc20660b2cf299183f403d289606dc81894e
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=5B788C20E1E2846E7CBB769
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=35535f9ded87a294a1241de92b97d09def9f8b3e
    [mt76_connac_lib]=419e748c56f4644d3a5d158fefbbb7e40650215e
    [mt792x_lib]=c12dd81205eb90a06c8a1a78f6274d6bd1c20d3d
    [mt7925_common]=c17e7f120c29f61d6a93302d2fbe5b14fa9b1602
    [mt7925e]=46eda30968d9284a408cfbe70180317814db62a0
)
;;
upstream-prefix22-secondary-trace)
declare -A candidate_hash=(
    [mt76]=0b7e081f8d7df9d81a80ce2add5d66c9a55e009eb710047472d7ee9b45294943
    [mt76_connac_lib]=7bfb92ebb730466e96221162a0ad181242f6e389080d30b57bfbfec33fe9d4a1
    [mt792x_lib]=ffc614fd400c944b289ef2dacb3b7ef9c384ff913d6de1a2c9a8553893ddf79a
    [mt7925_common]=f9ebd3413117ae34cd4a2946dda4a070b8617460835ac8521aa637d9cebddc07
    [mt7925e]=67a6f571f3c6b85ae4eaf0895dc34d36ea6e60958262d4a16549efa7490feeef
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=A53CAB3281ACA3A1A6844CB
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=0a4ab14f434535f7061ef9c30cab6f6940f4d552
    [mt76_connac_lib]=a7c1d95f680708fee06a30d114bc9280548bf1e3
    [mt792x_lib]=f0c375636bf2ef6ebc33b68d09c1b11f09e5185e
    [mt7925_common]=2db5ef86a4cbb2f288fa8028afb65acebb190520
    [mt7925e]=08cff84de82e86fe0627b62d3cd8075ecef53408
)
;;
upstream-prefix22-assoc-eml-trace)
declare -A candidate_hash=(
    [mt76]=19f7be53ae9be7f423abacfadbadc5c1a052901c8fb0c6d08a6171ec6ea1d014
    [mt76_connac_lib]=cd6555e68e8d52d0456a146e0d1bd5bc9ecce4c751e0fc08b7dc358e3b7df92e
    [mt792x_lib]=6207e866a76840378d7f40a1ff0360e009f313b6372af06e6686fef56c25274a
    [mt7925_common]=c7e50b29d0abdc20036d0669d1ee4d19d4feff424f6c4340be0cbea8e83f5634
    [mt7925e]=d54949befb950ce8ef80e0dd74ebf4b0229ada656bcdac53f0c4720f22ea8ece
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=CC2EACF2D6ABE3B6E9C8B76
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=4d21280326958eb314e67041e536500b5c1b142d
    [mt76_connac_lib]=d7f32dcad51d9738d86e7025928132dfe3a887b6
    [mt792x_lib]=6eba60febce12b30ae85cc2f0d74214967090f3c
    [mt7925_common]=7212436f0403103f9a08b0be134ca459b4988f4e
    [mt7925e]=628910d38f0a42c1737c27af6300d3bd48f439f3
)
;;
upstream-prefix22-primary-trace)
declare -A candidate_hash=(
    [mt76]=dd4e8fdb2898310bae91f8ee37843c0fbc0063aaaad9f4fff1cf4eefda542be6
    [mt76_connac_lib]=c834b247528a87d618ff989df3b8b7abea19489a308e1d86f7e1caf72d63738b
    [mt792x_lib]=8e841ae376eeb06f2b3972bd190b3ccf6db7893ae16b38ae16fba8c214d3f07b
    [mt7925_common]=3a925db740974775857a935567d99e962429390bef242d97dd4249fc05cc2de5
    [mt7925e]=55ed4ecbe2a2088a10aa2f9ea7033888ffe2711ad1b1b6521febd1c85d0a4cc8
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=5874D3F6060311D860907C3
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=d6a4ef31ea67087f50bc3efa1a5d2bab9cc4351a
    [mt76_connac_lib]=a524279c9c051984b3f02697c1472eae241b3c88
    [mt792x_lib]=0868bd3741d96ebee25c0bd32a4f67c6eb50f3b3
    [mt7925_common]=eeaa318c0be995d7b48bb19eb3178818f58f42c8
    [mt7925e]=41e94948ee0fad810bba2eb8332dee55357fbdd5
)
;;
upstream-prefix22-bss-trace)
declare -A candidate_hash=(
    [mt76]=ed0886eaaa97f0b7039c0ada88489f6aa6ccb7659a988c4d1ce976c30d767f18
    [mt76_connac_lib]=1b7eb6cbbbf9a67a465fc0a4a0a3909f12fdb241e8a0d792b31832c7142e85be
    [mt792x_lib]=e4bc58fb67a35ec40307c73c622af26804b51c83ea25c57145c43c29b62fb3f5
    [mt7925_common]=97d812a745b910eaa46de101a69ff29dff6c5eb3783caf3691588fc0f35c7ffe
    [mt7925e]=8c507fd0afbe00a140472a99eaed84d83a98bab605bfbc1c70137f0c233e62c3
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=7D191C51FB99E747CE27407
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=e5152e271488cbee03f923527b70e03b27f733c2
    [mt76_connac_lib]=b3c16310557f72598299adbc9f05059ba2176ff2
    [mt792x_lib]=442b192c413ea855a3af399c364222e33605def4
    [mt7925_common]=ad610befe52c29f0b43851ad7e6629cc3cd131ce
    [mt7925e]=c894fa55228c6fc36f3ef4f21ea8a32f11e57fa8
)
;;
upstream-prefix23)
declare -A candidate_hash=(
    [mt76]=15e03bce2e5814e2394a2941eb40413433984d9ba02671596a10db5fa5eaff58
    [mt76_connac_lib]=4eb1571db511039409fb2d3facab29d109046983643af7215a7ab0d4a5a7c75c
    [mt792x_lib]=4bc0019a94ba540f662f14bf0f6a4840eb8c6ef8a050940461927c9e4885ffe4
    [mt7925_common]=06444265c225bf04b16401e544f5b8b4640f08645ab6a95f603796e7c3f27839
    [mt7925e]=184ee86570cf94d2abf9e2b8ce98de20b59a4994e5fb9eafa6421061002126a0
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=100D6C0163D39BCE008410D
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=5341a96d22bf47573992ec0d5b6d3a714b4330ee
    [mt76_connac_lib]=39c0e201d49740bfbabd443f27a9acaf00788069
    [mt792x_lib]=aa2dc137e393f33cc380c2a6ed5cc37b4fc20e10
    [mt7925_common]=403a91903e14bcccbf7d727f8b2027f87b62013b
    [mt7925e]=94468dc6024a95ac45aa8175bc783bb20b402f4a
)
;;
upstream-prefix23-trace)
declare -A candidate_hash=(
    [mt76]=0a2f906db471ff0755fcab452f9b55d7d30c93d8ace4e57e2aa039fdd36970be
    [mt76_connac_lib]=5301b50cd508553cdc1b7a374e05f13086ba6bbd439c4970157d18c03553857e
    [mt792x_lib]=6b3d3cf316666dbe62c186d07c5b56907ec2a5fc8ae7f3cf7510907f77d2b211
    [mt7925_common]=2e881ecca3119685ddd7ab3caa9f258c31319f3308ca53b9f7b0e7a92389ae4d
    [mt7925e]=61bd44cb2757aa72cc663f47d731284b420ba3fbd3be3b3f8f02591f375114ce
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=12D80BEB68200F12F3BB55A
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=82f4d82c45eae0e2cd9a55dd38d2393300105186
    [mt76_connac_lib]=7d7e02cef4b91a9de70692a01bc9291ac78ada21
    [mt792x_lib]=4310c719e214cd87d6a9302f0fd75672bae1b3e0
    [mt7925_common]=c636f0539525c0531c028af496ce362a15715166
    [mt7925e]=f1b7d2a93fe56e8968698ce9e4ea883bb5d750e1
)
;;
upstream-prefix24)
declare -A candidate_hash=(
    [mt76]=f929e473d2eaefaa42beb2060906280f177a21bec22db07aa2079147697ab2ab
    [mt76_connac_lib]=3800b47c2e2c088f88bc4eed0dc3f1ccfc4ee07277b3f7caa59db46009b4e0b7
    [mt792x_lib]=afdb5842b0ba1256e8ad882aaf62a41723bed0dc3cfa3ea5d6a6c32692d6eb50
    [mt7925_common]=be1821cf31d44b780bcaa98c14b08e09004ae877c8a8b0ecea9ef40889ce78cd
    [mt7925e]=1b152364a21665c697b6e2f7f7c6582a27aa922ed7ea979ec62fe650aa2771f6
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=9FAF8F56A5317D3F0883990
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=81e0cffb11e04d485c3cca7d0cc98db861c7ddbd
    [mt76_connac_lib]=af4829695206e00797623d48ebd9288389820eaf
    [mt792x_lib]=570c3d1d44f134476ca846435477a6355be8a023
    [mt7925_common]=8761ca32f34a1294aa9e218c1b60242716122786
    [mt7925e]=0add8d2fa98cbdfaeef6b9522659be449a8fd3a7
)
;;
upstream-mlo)
declare -A candidate_hash=(
    [mt76]=c0c66bbdfeabd774ba2236c69bdec5c8e4bb3b37a4a54c629b41635bfa2baea5
    [mt76_connac_lib]=dcc942fdc3b0c3e26e25832b20b738e1bb5eed523675286d3e76e50561c073d9
    [mt792x_lib]=771a6caeabef3cf8b0cf22d2be51e89b51b076bf938895e41e6b129758d23e78
    [mt7925_common]=0ab5eceb65fade61650a3c32c6dff07af6b211b3283b4864bb89daaf39dc4f45
    [mt7925e]=7992986999d9cec7be3feb74a31279173a1bd21589a74695e0ee091b8c7d7db6
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=6B2DB0A319E60718A55A35B
    [mt7925e]=59C609541F7228695F13B8E
)
declare -A candidate_id=(
    [mt76]=a8291ddff22eadbb14b6f44d5200614f4db14b3d
    [mt76_connac_lib]=23ce263ab674f6005eaae7983db24cc4323f37a4
    [mt792x_lib]=2eb4ec10063d2f3b94713a2d54b34dfa2f78c633
    [mt7925_common]=279be35b30cf4b37b0597a22a08e63474e2b1bf2
    [mt7925e]=5ba0854aa38c909217516106f4f2df8a384a3906
)
        ;;
    *) exit 2 ;;
esac
if [[ $action == --trace-profile ]]; then
    printf '%s\n' "${trace_profiles[$variant]}"
    exit 0
fi
declare -A holders=(
    [mt76]='mt76_connac_lib,mt7925_common,mt7925e,mt792x_lib'
    [mt76_connac_lib]='mt7925_common,mt7925e,mt792x_lib'
    [mt792x_lib]='mt7925_common,mt7925e'
    [mt7925_common]=mt7925e
    [mt7925e]=''
)
hash() { sha256sum "$1" | cut -d' ' -f1; }
note_id() {
    local note
    note=$(od -An -v -tx1 "/sys/module/$1/notes/.note.gnu.build-id" | tr -d ' \n')
    [[ $note =~ ^040000001400000003000000474e5500([0-9a-f]{40})$ ]]
    printf '%s' "${BASH_REMATCH[1]}"
}
scope() {
    [[ $(uname -r) == "$kver" && $(cat /proc/sys/kernel/hostname) == wifi7-lab &&
       $(cat /sys/bus/pci/devices/0000:02:00.0/vendor) == 0x14c3 &&
       $(cat /sys/bus/pci/devices/0000:02:00.0/device) == 0x7925 &&
       $(ip -4 route get 10.1.0.2) == *'dev eno1 src 10.1.0.221 '* &&
       $(nmcli -g connection.autoconnect connection show Wave7-MLO-Lab) == no ]]
}
interface_ready() {
    [[ $(readlink -f /sys/class/net/wlp2s0/device) == "$(readlink -f /sys/bus/pci/devices/0000:02:00.0)" &&
       $(basename "$(readlink -f /sys/bus/pci/devices/0000:02:00.0/driver)") == mt7925e &&
       $(nmcli -g GENERAL.STATE device show wlp2s0) == '30 (disconnected)' ]]
}
watchdog_bus=(org.freedesktop.systemd1 /org/freedesktop/systemd1
    org.freedesktop.systemd1.Manager)
watchdog_path=/sys/class/watchdog/watchdog0
set_watchdog() {
    busctl set-property "${watchdog_bus[@]}" RuntimeWatchdogUSec t "$1"
}
check_watchdog() {
    local mode=$1 last_ping
    [[ $(cat "$watchdog_path/identity") == wdat_wdt &&
       $(cat "$watchdog_path/nowayout") == 0 ]]
    if [[ $mode == inactive ]]; then
        [[ $(busctl get-property "${watchdog_bus[@]}" RuntimeWatchdogUSec) == 't 0' &&
           $(cat "$watchdog_path/state") == inactive ]]
    else
        [[ $(busctl get-property "${watchdog_bus[@]}" RuntimeWatchdogUSec) == 't 60000000' &&
           $(cat "$watchdog_path/state") == active &&
           $(cat "$watchdog_path/timeout") == 60 ]]
        last_ping=$(busctl get-property "${watchdog_bus[@]}" WatchdogLastPingTimestampMonotonic)
        [[ $last_ping =~ ^t\ [0-9]+$ && $last_ping != 't 18446744073709551615' ]]
    fi
    printf 'HARDWARE_WATCHDOG_%s\n' "${mode^^}"
}
disk_original() {
    local name path
    for name in "${modules[@]}"; do
        path=$(modinfo -n "$name")
        [[ $(hash "$path") == "${original_hash[$name]}" &&
           $(modinfo -F srcversion "$path") == "${original_version[$name]}" ]]
        if [[ $name == mt7925_common ]]; then
            [[ $(readlink -f "$path") == /usr/lib/modules/"$kver"/updates/mt7925/mt7925-common.ko ]]
        else
            [[ $(readlink -f "$path") == /usr/lib/modules/"$kver"/kernel/drivers/net/wireless/mediatek/mt76/* ]]
        fi
    done
}
loaded_closure() {
    local variant=$1 name actual expected_version expected_id
    actual=$(awk '/^(mt76|mt792)/ {print $1}' /proc/modules | LC_ALL=C sort | paste -sd, -)
    [[ $actual == "$(printf '%s\n' "${modules[@]}" | LC_ALL=C sort | paste -sd, -)" ]]
    for name in "${modules[@]}"; do
        [[ $(find "/sys/module/$name/holders" -mindepth 1 -maxdepth 1 -printf '%f\n' |
              LC_ALL=C sort | paste -sd, -) == "${holders[$name]}" ]]
        if [[ $variant == original ]]; then
            expected_version=${original_version[$name]}
            expected_id=${original_id[$name]}
        else
            expected_version=${candidate_version[$name]}
            expected_id=${candidate_id[$name]}
        fi
        [[ $(cat "/sys/module/$name/srcversion") == "$expected_version" &&
           $(note_id "$name") == "$expected_id" ]]
        printf '%s srcversion=%s build_id=%s\n' "$name" "$expected_version" "$expected_id"
    done
}
candidate_files() {
    local dir=$1 name f
    for name in "${modules[@]}"; do
        f="$dir/${names[$name]}"
        [[ -f $f && ! -L $f &&
           $(hash "$f") == "${candidate_hash[$name]}" &&
           $(modinfo -F name "$f") == "$name" &&
           $(modinfo -F srcversion "$f") == "${candidate_version[$name]}" &&
           $(modinfo -F vermagic "$f") == "$kver SMP preempt mod_unload " &&
           $(llvm-readelf -n "$f" | awk '/Build ID:/ {print $3}') == "${candidate_id[$name]}" ]]
        printf 'candidate %s sha256=%s\n' "$name" "${candidate_hash[$name]}"
    done
}
check_original() {
    scope
    interface_ready
    [[ -z $(cat /sys/module/firmware_class/parameters/path) ]]
    check_watchdog inactive
    disk_original
    loaded_closure original
    local other
    for other in "${variants[@]}"; do
        [[ ! -e /run/wave7-$other-stack ]]
        if systemctl is-active --quiet "wave7-$other-rollback.timer"; then return 1; fi
    done
    printf 'STACK_ORIGINAL_PASS boot=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
}
check_firmware_bundle() {
    local dir=$1
    local root=$dir/mediatek/mt7925
    local ram=$root/WIFI_RAM_CODE_MT7925_1_1.bin
    local patch=$root/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin
    [[ -f $ram && ! -L $ram && $(hash "$ram") == "$firmware_ram_sha" &&
       -f $patch && ! -L $patch && $(hash "$patch") == "$firmware_patch_sha" ]]
}
check_candidate() {
    scope
    interface_ready
    if [[ $variant == "$firmware_variant" ]]; then
        [[ $(cat /sys/module/firmware_class/parameters/path) == "$stage/firmware" ]]
        check_firmware_bundle "$stage/firmware"
        [[ $(stat -c '%u:%g:%a' "$stage/firmware/mediatek/mt7925/WIFI_RAM_CODE_MT7925_1_1.bin") == 0:0:644 &&
           $(stat -c '%u:%g:%a' "$stage/firmware/mediatek/mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin") == 0:0:644 ]]
    else
        [[ -z $(cat /sys/module/firmware_class/parameters/path) ]]
    fi
    check_watchdog active
    disk_original
    [[ $(stat -c '%u:%g:%a' "$stage") == 0:0:755 &&
       $(cat "$stage/boot") == "$(cat /proc/sys/kernel/random/boot_id)" ]]
    systemctl is-active --quiet "$timer"
    candidate_files "$stage"
    loaded_closure candidate
    printf 'STACK_CANDIDATE_PASS variant=%s boot=%s\n' "$variant" "$(cat /proc/sys/kernel/random/boot_id)"
}
case "$action" in
    --check-original) check_original ;;
    --check-candidate) check_candidate ;;
    --activate)
        [[ $EUID == 0 ]]
        check_original
        candidate_files "$bundle"
        if [[ $variant == "$firmware_variant" ]]; then
            check_firmware_bundle "$firmware_source"
        fi
        [[ -z $(ls /sys/kernel/tracing/instances) &&
           $(cat /sys/kernel/tracing/current_tracer) == nop &&
           $(cat /sys/module/mt7925e/refcnt) == 0 ]]
        changed=0
        staged=0
        armed=0
        watchdog_armed=0
        cleanup() {
            local rc=$?
            trap - EXIT
            if (( rc != 0 )); then
                echo STACK_ACTIVATION_FAILED >&2
                if (( changed )); then
                    systemctl reboot --no-block || rc=1
                else
                    if (( watchdog_armed )); then set_watchdog 0 || rc=1; fi
                    if (( armed )); then systemctl stop "$timer" || rc=1; fi
                    if (( staged )); then rm -rf -- "$stage"; fi
                fi
            fi
            exit "$rc"
        }
        trap cleanup EXIT
        mkdir -m 0755 "$stage"
        staged=1
        for name in "${modules[@]}"; do
            install -m 0644 "$bundle/${names[$name]}" "$stage/${names[$name]}"
        done
        candidate_files "$stage"
        if [[ $variant == "$firmware_variant" ]]; then
            install -d -m 0755 "$stage/firmware/mediatek/mt7925"
            for filename in WIFI_RAM_CODE_MT7925_1_1.bin WIFI_MT7925_PATCH_MCU_1_1_hdr.bin; do
                install -m 0644 "$firmware_source/mediatek/mt7925/$filename" "$stage/firmware/mediatek/mt7925/$filename"
            done
            check_firmware_bundle "$stage/firmware"
        fi
        cat /proc/sys/kernel/random/boot_id > "$stage/boot"
        date +%s > "$stage/epoch"
        chmod 0644 "$stage"/{boot,epoch}
        systemd-run --quiet --collect --unit="wave7-$variant-rollback" \
            --on-active=15min --timer-property=AccuracySec=1s /usr/bin/systemctl reboot
        armed=1
        systemctl is-active --quiet "$timer"
        watchdog_armed=1
        set_watchdog 60000000
        check_watchdog active
        changed=1
        if [[ $variant == "$firmware_variant" ]]; then
            printf '%s' "$stage/firmware" > /sys/module/firmware_class/parameters/path
            [[ $(cat /sys/module/firmware_class/parameters/path) == "$stage/firmware" ]]
            printf 'FIRMWARE_OVERRIDE_PINNED sha_ram=%s sha_patch=%s
' "$firmware_ram_sha" "$firmware_patch_sha"
        fi
        for ((i=${#modules[@]}-1; i>=0; i--)); do rmmod "${modules[i]}"; done
        for name in "${modules[@]}"; do [[ ! -e /sys/module/$name ]]; done
        for name in "${modules[@]}"; do insmod "$stage/${names[$name]}"; done
        for _ in {1..60}; do
            if interface_ready; then break; fi
            sleep 1
        done
        check_candidate
        firmware=$(journalctl -k -b --no-pager --since "@$(cat "$stage/epoch")" |
            rg 'mt7925e.*(HW/SW Version|WM Firmware Version)')
        printf '%s\n' "$firmware"
        if [[ $variant == "$firmware_variant" ]]; then
            [[ $firmware == *20261016232915a* && $firmware == *20261016233029* ]]
        else
            [[ $firmware == *20260813113015a* && $firmware == *20260813113118* ]]
        fi
        trap - EXIT
        ;;
    --restore)
        [[ $EUID == 0 ]]
        check_candidate
        systemctl reboot --no-block
        ;;
    *) exit 2 ;;
esac
