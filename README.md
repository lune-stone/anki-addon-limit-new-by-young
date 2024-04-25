# Limit New by Young

Limit New by Young is an add-on for [Anki](https://github.com/ankitects/anki) that can aid in maintaining a stable and efficient daily workload.

Anki already includes settings that can limit both new and reviewed cards by the number of cards that are due for the day, but this kind of limit is not always ideal. If instead you place a limit on the total number of young cards, then you will be fed new cards at roughly the same rate that you learn them. This removes the need to do manually tuning to reach an optimal balance point.

## Features

* Limit new card by young cards in deck
* Limit new card by estimated daily review load
* Limit new card by cards that will be due soon
* Different types of limits can be combined on a deck
* Defined limits rules can apply to an individual deck or groups of decks
* Options to automatically apply limits
* UI tools to review limits and how close each deck is to it's limits

## Setup

To install go to [ankiweb.net](https://ankiweb.net/shared/info/214963846) and follow the instructions in the `Download` section.

After installing the add-on you will need to define a limit for one or more decks for the add-on to work. This is done by going to `Tools > Add-ons` selecting this add-on by name then clicking the `Config` button. Next edit the configuration json to add a limit. For example if you want to limit every decks to have at most 50 young cards you would edit the `"limits"` section to look like this:

```
"limits": [
    {
        "deckNames": ".*",
        "youngCardLimit": 50
    }
],
```

For more customization of limits read through and follow the instructions on the right size of the screen. Lastly to apply the limits you can either use the configuration to enable automatic updates, or manually trigger an update by using `Tools > Limit New by Young > Recalculate today's new card limit for all decks` from the menu.

To undo the limits you can either set the `New cards/day` limit under `Today only` or switch back to `Preset` found in the deck's options.

## Support

For any questions, problems, or other feedback feel free to create an issue on [github](https://github.com/lune-stone/anki-addon-limit-new-by-young) or leave a comment on [ankiweb.net](https://ankiweb.net/shared/info/214963846).
