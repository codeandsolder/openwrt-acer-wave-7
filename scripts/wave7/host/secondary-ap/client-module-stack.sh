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
    [upstream-prefix22-dev-band-trace]=association-dev-band
    [upstream-prefix22-secondary-first-trace]=association
    [upstream-prefix22-secondary-trace]=association
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
    disk_original
    loaded_closure original
    local other
    for other in "${variants[@]}"; do
        [[ ! -e /run/wave7-$other-stack ]]
        if systemctl is-active --quiet "wave7-$other-rollback.timer"; then return 1; fi
    done
    printf 'STACK_ORIGINAL_PASS boot=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
}
check_candidate() {
    scope
    interface_ready
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
        [[ -z $(ls /sys/kernel/tracing/instances) &&
           $(cat /sys/kernel/tracing/current_tracer) == nop &&
           $(cat /sys/module/mt7925e/refcnt) == 0 ]]
        changed=0
        staged=0
        armed=0
        cleanup() {
            local rc=$?
            trap - EXIT
            if (( rc != 0 )); then
                echo STACK_ACTIVATION_FAILED >&2
                if (( changed )); then
                    systemctl reboot --no-block
                else
                    if (( armed )); then systemctl stop "$timer"; fi
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
        cat /proc/sys/kernel/random/boot_id > "$stage/boot"
        date +%s > "$stage/epoch"
        chmod 0644 "$stage"/{boot,epoch}
        systemd-run --quiet --collect --unit="wave7-$variant-rollback" \
            --on-active=15min --timer-property=AccuracySec=1s /usr/bin/systemctl reboot
        armed=1
        systemctl is-active --quiet "$timer"
        changed=1
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
        [[ $firmware == *20260813113015a* && $firmware == *20260813113118* ]]
        trap - EXIT
        ;;
    --restore)
        [[ $EUID == 0 ]]
        check_candidate
        systemctl reboot --no-block
        ;;
    *) exit 2 ;;
esac
