from conciliador_core.documents import (
    cnpj_root,
    find_documents,
    is_valid_cnpj,
    is_valid_cpf,
    mask_cpf,
    only_alnum,
)


def test_cpf() -> None:
    assert is_valid_cpf("529.982.247-25")
    assert is_valid_cpf("52998224725")
    assert not is_valid_cpf("529.982.247-24")
    assert not is_valid_cpf("111.111.111-11")
    assert not is_valid_cpf("5299822472")


def test_cnpj_numeric_and_alphanumeric() -> None:
    assert is_valid_cnpj("11.222.333/0001-81")
    assert is_valid_cnpj("12.ABC.345/01DE-35")
    assert is_valid_cnpj("12abc34501de35")
    assert not is_valid_cnpj("11.222.333/0001-80")
    assert not is_valid_cnpj("00.000.000/0000-00")
    assert not is_valid_cnpj("12.ABC.345/01DE-3A")
    assert not is_valid_cnpj("1122233300018")
    assert cnpj_root("12.abc.345/01de-35") == "12ABC345"


def test_only_alnum() -> None:
    assert only_alnum("12.abc.345/01de-35") == "12ABC34501DE35"


def test_find_documents_only_valid_in_order() -> None:
    memo = "PIX REC 52998224725 MARIA / 11222333000181 / 12345678901"
    assert find_documents(memo) == ("52998224725", "11222333000181")


def test_find_documents_formatted_and_alphanumeric() -> None:
    memo = "PAG 12.ABC.345/01DE-35 e CPF 529.982.247-25"
    assert find_documents(memo) == ("12ABC34501DE35", "52998224725")


def test_find_documents_ignores_substring_of_longer_run() -> None:
    # 11 digits valid CPF embedded in a longer digit run must not be reported
    assert find_documents("X1111222333000181") == ()
    assert find_documents("529982247251") == ()
    assert find_documents("A52998224725") == ()


def test_find_documents_empty() -> None:
    assert find_documents("") == ()


def test_mask_cpf() -> None:
    assert mask_cpf("52998224725") == "***.982.247-**"
    assert mask_cpf("529.982.247-25") == "***.982.247-**"
