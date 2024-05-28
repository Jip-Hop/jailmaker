# Jailmaker Docs

## ZFS Datasets Migration

From version 1.1.4 ZFS Datasets support was added to jailmaker.
By default starting in v1.1.4, jailmaker will create a separate dataset for each jail if possible. This allows the user to configure snapshots, rollbacks, replications etc.

Jailmaker operates in dual-mode: it supports using both directories and datasets. If the 'jailmaker' directory is a dataset, it will use datasets, if it is a directory, it will use directories.

### Procedure to migrate from directories to ZFS Datasets

#### Stop all jails

`./jlmkr.py stop jail1`

`./jlmkr.py stop jail2`
etc..

#### Move/rename the 'jailmaker' directory

`mv jailmaker orig_jailmaker`

#### Create the ZFS datasets for jailmaker

Create all the required datasets via GUI or CLI.

You need to create the following datasets:

`jailmaker`

`jailmaker/jails`

And one for each existing jail:

`jailmaker/jails/jail1`

`jailmaker/jails/jail2`
etc.


Via CLI:
```
zfs create mypool/jailmaker
zfs create mypool/jailmaker/jails
zfs create mypool/jailmaker/jails/jail1
zfs create mypool/jailmaker/jails/jail2
```

#### Move the existing jail data into the newly created datasets

Now move all the jail data:

`rsync -av orig_jailmaker/ jailmaker/`

Warning! It's important that both directories have the `/` at the end to make sure contents are copied correctly. Otherwise you may end up with `jailmaker/jailmaker`

#### Test everything works

If everything works, you should be able to use the `./jlmkr.py` command directly. Try doing a `./jlmkr.py list` to check if the jails are correctly recognized

You can also try creating a new jail and see that the dataset is created automatically.