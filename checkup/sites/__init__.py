from checkup.sites import pokemoncenter

# Map of check type (as used in config.yaml) -> function(fetcher, target) -> dict of signals
CHECKS = {
    "pokemoncenter.queue": pokemoncenter.check_queue,
    "pokemoncenter.product": pokemoncenter.check_product,
}
