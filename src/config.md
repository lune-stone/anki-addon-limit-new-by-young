## Configuration on this Screen

### `limits`

A list of configurations containing info on what limit(s) to apply to which deck(s). A deck will only use the first configuration in the list that matches it's name.

### `deckNames`

Used to control which decks the limit applies to. Can either be a list containing the deck names, or a regular expression string containing the pattern to match deck names. Using `"deckNames": ".*"` as the last configuration can serve as a way to have a 'default' configuration for all remaining decks.

When creating a limit for a specific sub-deck use the full name including the `::` delimiters between parent/child names (ex: `deckNames: ["lorem ipsum 1::part 1::chapter 2"]`). When calculating limits for a deck, all cards from child decks are included in calculations (same as how Anki v3 limits works).

### `youngCardLimit`

A positive integer that represents the number of young cards that the deck should not go over when adding new cards for the day. This value does not replace existing daily limits on new cards but will work together with them. For example if there are too many reviews in addition to too many young cards for today, then the new card limit for the day will be set to the minimum value between the two limits.

If you do not wish to limit the number of young cards, but plan on using other types of limits then you can either remove the `youngCardLimit` key from the json object, or set the value above the deck size.

Picking the value to use as the limit can be tricky as the ideal value will vary from person to person as well as deck to deck. If you have one or more days were your new cards are being limited but you do well on your reviews and still have time to spare then consider raising the limit. If instead you find that your retention on young cards is not as high as retention for mature cards you may need to reduce the value.

### `loadLimit`

A positive integer that represents the upper limit for a reviews/day load of a deck based on the "daily load" estimate from fsrs4anki-helper. You can view this value by installing fsrs4anki-helper, then loading the legacy stats view for the click using `shift+click` on the `stats` tab. Limiting by load rather than reviews can sometimes be useful if for example you have a large backlog of reviews but want to continue studying new material while you catch up. New cards will be limited each day by the difference between `loadLimit` and the calculated deck load value. This limit does not replace existing daily limits on new cards but will work together with them. For example if there are too many reviews in addition to too much load for today, then the new card limit for the day will be set to the minimum value between the two limits.

If you do not wish to limit the max load for the deck, but plan on using other types of limits then you can either remove the `loadLimit` key from the json object, or set the value above the deck size.

### `soonLimit`

A positive integer that represents the upper limit for how many upcoming cards of a deck in the next n days where n is determined by the value of `soonDays`. This value does not replace existing daily limits on new cards but will work together with them. For example if there are too many reviews in addition to too much cards becoming due in the near future, then the new card limit for the day will be set to the minimum value between the two limits.

If you do not wish to limit the number of young cards, but plan on using other types of limits then you can either remove the `soonLimit` key from the json object, or set the value above the deck size.

### `soonDays`

A positive integer that represents how many days to include when calculating cards that are due soon for `soonLimit`. Default value is `7` if not defined in the config json. This value has no effect if `soonLimit` is not defined.

### `updateLimitsOnApplicationStartup`

When using `true` the add-on will automatically update the new card limit when Anki is launched. If today's limit has already been set then the limit will not be updated a second time. If you are using sync between multiple devices then it is recommend to use `updateLimitsAfterSync` instead.

### `updateLimitsAfterSync`

When using `true` the add-on will automatically update the new card limit after a sync is preformed. If today's limit has already been set then the limit will not be updated a second time.

### `updateLimitsOnInterval`

When using `true` the add-on will automatically update the new card limit even time equal to `updateLimitsIntervalTimeInMinutes` has elapsed. If today's limit has already been set then the limit will not be updated a second time. This can be useful if you leave Anki open overnight.

### `updateLimitsIntervalTimeInMinutes`

When `updateLimitsOnInterval` is set to true, the time in minutes in between updating the new card limit. If `updateLimitsOnInterval` is false, this setting has no effect.

### `showNotifications`

When `showNotifications` is set to true, a notification will be shown at the start and end of the process each time limits are updated.
