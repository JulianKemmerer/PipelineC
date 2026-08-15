{
  lib,
  stdenv,
  fetchPypi,
  python3,
  makeWrapper,
  ghdl,
  yosys,
  yosys-ghdl,
  gcc,
  coreutils,
}:

let
  pyrtl = python3.pkgs.buildPythonPackage rec {
    pname = "pyrtl";
    version = "0.11.3";
    pyproject = true;

    src = fetchPypi {
      inherit pname version;
      hash = "sha256-F+2L55HPe1N7FuhWRlonSeB8FArOgVu54QATKn/0Otk=";
    };

    build-system = with python3.pkgs; [
      hatchling
      hatch-vcs
    ];
    dependencies = [ python3.pkgs.pyparsing ];
    doCheck = false;
    pythonImportsCheck = [ "pyrtl" ];
  };

  python = python3.withPackages (ps: [
    ps.setuptools
    ps.pyparsing
    pyrtl
  ]);
in
stdenv.mkDerivation {
  pname = "pipelinec";
  version = (lib.importTOML ../pyproject.toml).tool.poetry.version;
  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      (lib.fileset.gitTracked ../.)
      ../default.nix
      ./package.nix
    ];
  };

  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/lib/pipelinec" "$out/bin"
    cp -r . "$out/lib/pipelinec"

    for compiler in pipelinec pypelinec; do
      makeWrapper ${python}/bin/python3 "$out/bin/$compiler" \
        --add-flags "$out/lib/pipelinec/src/$compiler" \
        --prefix PATH : ${
          lib.makeBinPath [
            python
            ghdl
            yosys
            gcc
          ]
        } \
        --set PYTHONPATH "$out/lib/pipelinec/src:$out/lib/pipelinec/include/pypeline" \
        --set PIPELINEC_YOSYS_GHDL_PLUGIN "${yosys-ghdl}/share/yosys/plugins/ghdl.so" \
        --run "if [ ! -d .pipelinec_path_delay_cache ]; then ${coreutils}/bin/cp -r '$out/lib/pipelinec/path_delay_cache' .pipelinec_path_delay_cache && ${coreutils}/bin/chmod -R u+w .pipelinec_path_delay_cache; fi" \
        --run 'export PIPELINEC_PATH_DELAY_CACHE_DIR="$PWD/.pipelinec_path_delay_cache/"'
    done

    runHook postInstall
  '';

  meta = {
    description = "PipelineC and Pypeline HDL toolchain with automatic pipelining";
    homepage = "https://github.com/JulianKemmerer/PipelineC";
    license = lib.licenses.gpl3;
    platforms = lib.platforms.linux;
  };
}
