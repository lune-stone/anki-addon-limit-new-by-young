## Configure in this screen

### `limits`

A list of configurations containing info on what limit(s) to apply to which deck(s). A deck will only use the first configuration in the list that matches it's name.

### `deckNames`

Used to control which decks the limit applies to. Can either be a list containing the deck names, or a regular expression string containing the pattern to match deck names. Using `"deckNames": ".*"` as the last configuration can serve as a way to have a 'default' configuration for all remaining decks.

When creating a limit for a specific sub-deck use the full name including the `::` delimiters between parent/child names (ex: `deckNames: ["lorem ipsum 1::part 1::chapter 2"]`). When calculating limits for a deck, all cards from child decks are included in calculations (same as how Anki v3 limits works).

### `youngCardLimit`

A positive integer that represents the number of young cards that the deck should not go over when adding new cards for the day. This value does not replace existing daily limits on new cards but will work together with them. For example if there are too many reviews in addition to too many young cards for today, then the new card limit for the day will be set to the minimum value between the two limits.

### `updateLimitsOnApplicationStartup`

When using `true` the add-on will automatically update the new card limit when Anki is launched. If today's limit has already been set then the limit will not be updated a second time. If you are using sync between multiple devices then it is recommend to use `updateLimitsAfterSync` instead.

### `updateLimitsAfterSync`

When using `true` the add-on will automatically update the new card limit after a sync is preformed. If today's limit has already been set then the limit will not be updated a second time.

### `updateLimitsOnInterval`

When using `true` the add-on will automatically update the new card limit even time equal to `updateLimitsIntervalTimeInMinutes` has elapsed. If today's limit has already been set then the limit will not be updated a second time. This can be useful if you leave Anki open overnight.

### `updateLimitsIntervalTimeInMinutes`

When `updateLimitsOnInterval` is set to true, the time in minutes in between updating the new card limit. If `updateLimitsOnInterval` is false, this setting has no effect.
