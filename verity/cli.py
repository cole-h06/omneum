import typer

from verity.deployment import DeploymentConfig, save_config
from verity.paths import get_config_dir, get_key_dir
from verity.provision import generate_deployment_id
from verity.keys import generate_voprf_key_material, encode_public_key

app = typer.Typer()


@app.callback()
def main() -> None:
    """Verity command-line interface."""
    pass


@app.command()
def init() -> None:
    """Initialize a Verity deployment."""
    config_dir = get_config_dir()
    key_dir = get_key_dir()

    if (config_dir / "config.toml").exists():
        typer.echo("Verity is already initialized.")
        typer.echo(f"Configuration: {config_dir}")
        typer.echo(f"Keys: {key_dir}")
        raise typer.Exit()

    deployment_id = generate_deployment_id()

    key_material = generate_voprf_key_material()

    config = DeploymentConfig(
        deployment_id=deployment_id,
        voprf_key_version=1,
        voprf_public_key=encode_public_key(
            key_material.public_key,
        ),
    )

    save_config(config)

    typer.echo("Verity initialized.")
    typer.echo(f"Deployment: {deployment_id}")
    typer.echo(f"Configuration: {config_dir}")
    typer.echo(f"Keys: {key_dir}")


if __name__ == "__main__":
    app()