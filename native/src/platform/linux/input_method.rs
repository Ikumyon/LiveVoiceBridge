use std::env;

pub(super) fn configure() {
    let selected = env::var_os("QT_IM_MODULE")
        .filter(|value| !value.is_empty())
        .or_else(|| match env::var("XMODIFIERS").as_deref() {
            Ok("@im=fcitx") => Some("fcitx".into()),
            Ok("@im=ibus") => Some("ibus".into()),
            _ => None,
        });

    if let Some(selected) = selected {
        // QApplicationとアプリのワーカースレッドを起動する前に、プロセス内の指定を揃える。
        env::set_var("QT_IM_MODULE", &selected);
        env::set_var("QT_IM_MODULES", &selected);
    }
}
